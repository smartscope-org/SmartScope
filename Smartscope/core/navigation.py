from typing import Optional, Iterable, Tuple
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from .models import AutoloaderGrid
from .status import status
from Smartscope.core.models.high_mag import HighMagModel
from Smartscope.sim_siam.plugin import SimSiamEmbedding
import numpy as np
from scipy.spatial.distance import cdist
from django.contrib.contenttypes.models import ContentType
from Smartscope.core.models.target_label import Finder
from Smartscope.core.models.hole import HoleModel as HoleModelClass

logger = logging.getLogger(__name__)


class TargetPriority(Enum):
    HOLE = 'hole'
    SQUARE = 'square'

@dataclass
class NavigationStrategy(ABC):
    grid: AutoloaderGrid

    @abstractmethod
    def get_hole_queue(self) -> Iterable:
        """Get the queue of holes for the given grid."""
        pass

    @abstractmethod
    def get_square_queue(self) -> Iterable:
        """Get the queue of squares for the given grid."""
        pass

@dataclass
class OriginalNavigationStrategy(NavigationStrategy):

    def get_hole_queue(self):
        return self.grid.holemodel_set.filter(selected=True, square_id__status=status.COMPLETED).\
            exclude(status__in=[status.SKIPPED, status.COMPLETED]).\
            order_by('square_id__completion_time', 'number')

    def get_square_queue(self):
        return self.grid.squaremodel_set.filter(selected=True).\
            exclude(status__in=[status.SKIPPED, status.COMPLETED, status.ERROR]+status().in_flight_statuses).\
            order_by('number')
            

def get_target_priority(grid:AutoloaderGrid, forced_priority:Optional[TargetPriority]=None):
    if grid.collection_mode == 'collection' or grid.session_id.microscope_id.vendor == 'JEOL':
        return TargetPriority.SQUARE
    if forced_priority is not None:
        return forced_priority
    if grid.collection_mode == 'screening':
        return TargetPriority.HOLE
    raise ValueError(f"Could not determine target priority for grid.")

def get_queue(grid, target_priority: TargetPriority, navigation_strategy=None, attempts: int = 0) -> Tuple[Iterable, NavigationStrategy]:
    if attempts == 2:
        return None, navigation_strategy
    
    if target_priority == TargetPriority.SQUARE:
        queue = navigation_strategy(grid).get_square_queue()
        if len(queue) ==  0:
            return get_queue(grid, TargetPriority.HOLE, navigation_strategy=navigation_strategy, attempts=attempts + 1)
    
    if target_priority == TargetPriority.HOLE:
        queue = navigation_strategy(grid).get_hole_queue()
        if len(queue) == 0:
            return get_queue(grid, TargetPriority.SQUARE, navigation_strategy=navigation_strategy, attempts=attempts + 1)
    
    logger.info(f'Queued => {target_priority}: {queue[0]}')
    return queue, target_priority

NAVIGATION_STRATEGIES = {
    'original': OriginalNavigationStrategy,
}

@dataclass
class NextPYPNavigationStrategy(NavigationStrategy):
    def _normalize(self, arr):
        mn, mx = arr.min(), arr.max()
        if mx == mn:
            return np.zeros_like(arr, dtype=float)
        return (arr - mn) / (mx - mn)

    def get_square_queue(self):
        return OriginalNavigationStrategy(self.grid).get_square_queue()
    
    def get_hole_queue(self):
        # Get list of all completed holes
        candidates = self.grid.holemodel_set.filter(
            selected=True,
            square_id__status=status.COMPLETED
        ).exclude(
            status__in=[status.SKIPPED, status.COMPLETED]
        )

        fallback = candidates.order_by('square_id__completion_time', 'number')

        # Get good holes from nextpyp pre-processing
        good_hole_ids = list(
            HighMagModel.objects.filter(
                grid_id=self.grid,
                classifiers__label='Good',
                classifiers__method_name='nextPYP Curation'
            ).values_list('hole_id', flat=True)
        )
        if not good_hole_ids:
            return fallback
        
        simsiam = SimSiamEmbedding()
        if not simsiam.is_embedding_data(self.grid, 'hole'):
            return fallback
        
        # Retrieve SimSiam hole quality info
        # Dataframe indexed hole_id, column 'embeddings'
        embeddings_df = simsiam.load_data(self.grid, 'hole')

        candidate_ids = list(candidates.values_list('hole_id', flat=True))
        cand_mask = embeddings_df.index.isin(candidate_ids)
        good_mask  = embeddings_df.index.isin(good_hole_ids)

        if not good_mask.any() or not cand_mask.any():
            return fallback
        
        cand_df = embeddings_df[cand_mask]
        good_emb = np.array(embeddings_df[good_mask]['embeddings'].to_list())
        cand_emb = np.array(cand_df['embeddings'].to_list())

        visual_score = cdist(cand_emb, good_emb, metric='euclidean').min(axis=1)

        # Retrieve distance scores
        hole_ct = ContentType.objects.get_for_model(HoleModelClass)

        finders_qs = Finder.objects.filter(
            content_type=hole_ct,
            object_id__in=list(cand_df.index)
        ).values('object_id', 'stage_x', 'stage_y')
        stage_by_id = {f['object_id']: np.array([f['stage_x'], f['stage_y']]) for f in finders_qs}

        last_hole = HoleModelClass.objects.filter(
            grid_id=self.grid,
            status=status.COMPLETED
        ).order_by('-completion_time').first()

        if last_hole is not None:
            last_finder = Finder.objects.filter(
                content_type=hole_ct,
                object_id=last_hole.hole_id
            ).first()
            if last_finder is not None:
                last_pos = np.array([last_finder.stage_x, last_finder.stage_y])
                prox_scores = np.array([
                    np.linalg.norm(stage_by_id[hid] - last_pos)
                    if hid in stage_by_id else np.inf
                    for hid in cand_df.index
                ])
            else:
                prox_scores = None
        else:
            prox_scores = None

        norm_visual = self._normalize(visual_score)
        combined = norm_visual

        if prox_scores is not None:
            combined += self._normalize(prox_scores)

        # Build BIS scores
        bis_radius = self.grid.params_id.bis_max_distance
        if bis_radius > 0:
            stage_coords = np.array([
                stage_by_id[hid]
                if hid in stage_by_id else np.array([np.inf, np.inf])
                for hid in cand_df.index
            ])
            dist_matrix = cdist(stage_coords, stage_coords) # Distance from hole to every other hole

            # Determine a neighborhood of BIS scores
            neighbor_mask = (dist_matrix < bis_radius) & (dist_matrix > 0) # Exclude self
            bis_yield = neighbor_mask @ norm_visual # Lower visual distance is better

            combined += self._normalize(bis_yield)

        scores_by_id = dict(
            zip(cand_df.index, combined)
        )

        # Holes with no embedding go to the end
        return sorted(
            list(candidates),
            key=lambda h: scores_by_id.get(h.hole_id, float('inf'))
        )