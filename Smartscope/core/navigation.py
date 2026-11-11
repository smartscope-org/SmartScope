from typing import Optional, Iterable, Tuple
import json
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from itertools import groupby
from pathlib import Path
from .models import AutoloaderGrid
from .status import status
from Smartscope.core.models.high_mag import HighMagModel
from Smartscope.sim_siam.plugin import SimSiamEmbedding
import numpy as np
from scipy.spatial.distance import cdist
from django.contrib.contenttypes.models import ContentType
from Smartscope.core.models.target_label import Finder, Selector
from Smartscope.core.models.hole import HoleModel as HoleModelClass
from Smartscope.core.selector_sorter import initialize_selector
from Smartscope.core.settings.worker import SMARTSCOPE_CUSTOM_CONFIG, SMARTSCOPE_DEFAULT_CONFIG
from Smartscope.core.quality_probe import load_probes, calibrate

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


@dataclass
class RandomNavigationStrategy(NavigationStrategy):
    verbose_name = 'Random'
    description = 'Pick the next hole/square uniformly at random among the eligible targets.'

    def get_hole_queue(self):
        candidates = list(self.grid.holemodel_set.filter(selected=True, square_id__status=status.COMPLETED).
            exclude(status__in=[status.SKIPPED, status.COMPLETED]))
        random.shuffle(candidates)
        return candidates

    def get_square_queue(self):
        candidates = list(self.grid.squaremodel_set.filter(selected=True).
            exclude(status__in=[status.SKIPPED, status.COMPLETED, status.ERROR]+status().in_flight_statuses))
        random.shuffle(candidates)
        return candidates


@dataclass
class GreedyNavigationStrategy(NavigationStrategy):
    verbose_name = 'Greedy (nearest neighbor)'
    description = 'Visit the eligible target closest (by stage position) to the last completed one.'

    @staticmethod
    def _reference_coords(queryset):
        last = queryset.filter(status=status.COMPLETED).order_by('-completion_time').first()
        return last.stage_coords if last is not None else None

    def get_hole_queue(self):
        candidates = list(self.grid.holemodel_set.filter(selected=True, square_id__status=status.COMPLETED).
            exclude(status__in=[status.SKIPPED, status.COMPLETED]))
        reference = self._reference_coords(self.grid.holemodel_set)
        if reference is None:
            return sorted(candidates, key=lambda h: (h.square_id.completion_time, h.number))
        return sorted(candidates, key=lambda h: np.linalg.norm(h.stage_coords - reference))

    def get_square_queue(self):
        candidates = list(self.grid.squaremodel_set.filter(selected=True).
            exclude(status__in=[status.SKIPPED, status.COMPLETED, status.ERROR]+status().in_flight_statuses))
        reference = self._reference_coords(self.grid.squaremodel_set)
        if reference is None:
            return sorted(candidates, key=lambda s: s.number)
        return sorted(candidates, key=lambda s: np.linalg.norm(s.stage_coords - reference))


def probe_directories() -> Tuple[Path, ...]:
    directories = (SMARTSCOPE_DEFAULT_CONFIG / 'navigation_probes',)
    if str(SMARTSCOPE_CUSTOM_CONFIG) not in ('', '.'):
        directories = (SMARTSCOPE_CUSTOM_CONFIG / 'navigation_probes',) + directories
    return directories


_embeddings_cache = {}

def load_hole_embeddings(grid: AutoloaderGrid):
    """SimSiam hole embeddings as an (ids, array) pair, cached until the parquet changes."""
    file = grid.directory / 'sim_siam_embeddings_hole.parquet.zip'
    key = (str(file), file.stat().st_mtime)
    if key not in _embeddings_cache:
        df = SimSiamEmbedding().load_data(grid, 'hole')
        _embeddings_cache.clear()
        _embeddings_cache[key] = ({hole_id: i for i, hole_id in enumerate(df.index)},
                                  np.array(df['embeddings'].to_list(), dtype=float))
    return _embeddings_cache[key]


@dataclass
class ProbeGreedyNavigationStrategy(NavigationStrategy):
    verbose_name = 'Greedy (predicted quality + distance)'
    description = ('Score each eligible hole with the pretrained SimSiam quality probe(s), recalibrated on this '
                   'grid\'s curated micrographs once both good and bad ones exist, and visit the hole with the '
                   'best predicted P(good) minus a penalty for its distance from the last completed hole.')
    # Penalty for the farthest candidate, in units of P(good)
    distance_weight = 0.5
    # HighMag classifier methods whose Good/Bad labels are used to recalibrate the probes
    label_methods = ('Manual Curation', 'nextPYP Curation')

    def get_square_queue(self):
        return OriginalNavigationStrategy(self.grid).get_square_queue()

    def _grid_labels(self):
        """Hole-level labels on this grid: 1 if any of its micrographs is Good, else 0."""
        labels = {}
        rows = HighMagModel.objects.filter(
            grid_id=self.grid,
            classifiers__method_name__in=self.label_methods,
            classifiers__label__in=['Good', 'Bad'],
        ).values_list('hole_id', 'classifiers__label')
        for hole_id, label in rows:
            labels[hole_id] = max(labels.get(hole_id, 0), int(label == 'Good'))
        return labels

    def get_hole_queue(self):
        candidates = list(self.grid.holemodel_set.filter(selected=True, square_id__status=status.COMPLETED).
            exclude(status__in=[status.SKIPPED, status.COMPLETED]))
        fallback = sorted(candidates, key=lambda h: (h.square_id.completion_time, h.number))

        probes = load_probes(probe_directories())
        if not candidates or not probes or not SimSiamEmbedding().is_embedding_data(self.grid, 'hole'):
            return fallback
        index, embeddings = load_hole_embeddings(self.grid)
        probes = [probe for probe in probes if probe.emb_dim == embeddings.shape[1]]
        if not probes:
            logger.warning(f'No quality probe matches the {embeddings.shape[1]}-dim hole embeddings.')
            return fallback

        labels = {hole_id: label for hole_id, label in self._grid_labels().items() if hole_id in index}
        calibration = calibrate(probes, embeddings[[index[h] for h in labels]], np.array(list(labels.values())))
        if calibration is None:
            return fallback
        logger.info(f'Probe navigation: {calibration}')

        scored = [h for h in candidates if h.hole_id in index]
        unscored = [h for h in fallback if h.hole_id not in index]
        if not scored:
            return fallback
        score = calibration.predict(embeddings[[index[h.hole_id] for h in scored]])

        reference = GreedyNavigationStrategy._reference_coords(self.grid.holemodel_set)
        if reference is not None:
            distance = np.array([np.linalg.norm(h.stage_coords - reference) for h in scored])
            if distance.max() > 0:
                score = score - self.distance_weight * distance / distance.max()

        # Holes with no embedding go to the end
        return [scored[i] for i in np.argsort(-score, kind='stable')] + unscored


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
    'greedy': GreedyNavigationStrategy,
    'random': RandomNavigationStrategy,
    'probe_greedy': ProbeGreedyNavigationStrategy,
}

def load_navigation_strategy(file: Path) -> str:
    """Read the navigation strategy name saved for a grid. Defaults to 'original' if missing/unreadable."""
    if file.exists():
        try:
            return json.loads(file.read_text()).get('strategy', 'original')
        except Exception:
            logger.exception(f'Failed to parse navigation strategy file {file}, defaulting to original.')
    return 'original'

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
            bis_group_by_id = {
                row['hole_id']: row['bis_group']
                for row in candidates.filter(hole_id__in=list(cand_df.index)).values('hole_id', 'bis_group')
            }

            id_to_idx = {hid: i for i, hid in enumerate(cand_df.index)}
            bis_group_to_indices = {}
            for hid in cand_df.index:
                key = bis_group_by_id.get(hid) or hid  # None bis_group -> solo group
                bis_group_to_indices.setdefault(key, []).append(id_to_idx[hid])

            bis_avg = np.full(len(cand_df), 1.0) # Default: each BIS group has the worst visual score
            bis_count = np.ones(len(cand_df)) # Default: each BIS group contains only 1 hole

            for indices in bis_group_to_indices.values():
                avg_q = norm_visual[indices].mean()
                count = len(indices)
                for idx in indices:
                    bis_avg[idx] = avg_q
                    bis_count[idx] = float(count)

            combined += self._normalize(bis_avg)    # lower avg quality in group = better
            combined -= self._normalize(bis_count)  # more holes in group = better

        scores_by_id = dict(
            zip(cand_df.index, combined)
        )

        # Holes with no embedding go to the end
        return sorted(
            list(candidates),
            key=lambda h: scores_by_id.get(h.hole_id, float('inf'))
        )


@dataclass
class SelectorSorterNavigationStrategy(NavigationStrategy):

    def get_square_queue(self):
        return OriginalNavigationStrategy(self.grid).get_square_queue()

    def get_hole_queue(self):
        candidates = self.grid.holemodel_set.filter(
            selected=True,
            square_id__status=status.COMPLETED
        ).exclude(
            status__in=[status.SKIPPED, status.COMPLETED]
        )

        fallback = candidates.order_by('square_id__completion_time', 'number')
        candidate_list = list(candidates)

        if not candidate_list:
            return fallback

        hole_ct = ContentType.objects.get_for_model(HoleModelClass)
        candidate_ids = [h.hole_id for h in candidate_list]

        selector_names = list(
            Selector.objects.filter(
                content_type=hole_ct,
                object_id__in=candidate_ids
            ).values_list('method_name', flat=True).distinct()
        )

        if not selector_names:
            return fallback

        # Start all holes as good; any selector giving class 0 marks the hole bad
        is_good = {h.hole_id: True for h in candidate_list}

        for selector_name in selector_names:
            holes_with_selector = [
                h for h in candidate_list
                if any(s.method_name == selector_name for s in h.selectors.all())
            ]
            if not holes_with_selector:
                continue
            try:
                sorter = initialize_selector(self.grid, selector_name, holes_with_selector)
                for hole, good in zip(holes_with_selector, sorter.binarize()):
                    if not good:
                        is_good[hole.hole_id] = False
            except Exception as e:
                logger.warning(f'Selector {selector_name} failed during navigation: {e}')

        return sorted(candidate_list, key=lambda h: 0 if is_good[h.hole_id] else 1)


# NAVIGATION_STRATEGIES['nextpyp'] = NextPYPNavigationStrategy
# NAVIGATION_STRATEGIES['selector_sorter'] = SelectorSorterNavigationStrategy
