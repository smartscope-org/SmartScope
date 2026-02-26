from typing import Optional, Iterable, Tuple
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from .models import AutoloaderGrid
from .status import status

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
            exclude(status__in=[status.SKIPPED, status.COMPLETED]+status().in_flight_statuses).\
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
