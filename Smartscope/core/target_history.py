from typing import List
import logging
from dataclasses import dataclass, field
from .models import AutoloaderGrid, AtlasModel, SquareModel, HoleModel, Target
from .status import status
from .run_grid import TargetPriority

logger = logging.getLogger(__name__)   


def get_past_history(grid: AutoloaderGrid, num_targets: int = 10):
    recent_targets = list(HoleModel.objects.filter(grid_id=grid, status=status.COMPLETED, selected=True).order_by('-completion_time')[:num_targets])
    num_queried = len(recent_targets)
    if num_queried < num_targets:
        num_targets -= num_queried
        recent_targets += list(SquareModel.objects.filter(grid_id=grid,status=status.COMPLETED, selected=True).order_by('-completion_time')[:num_targets])
    num_queried = len(recent_targets)
    if num_queried < num_targets:
        recent_targets += list(AtlasModel.objects.filter(grid_id=grid,status=status.COMPLETED).order_by('-completion_time')[:num_targets])
    return sorted(recent_targets, key=lambda x: x.completion_time, reverse=True)

def get_current_target(grid: AutoloaderGrid):
    current_target = HoleModel.objects.filter(grid_id=grid,status__in=[status.STARTED,status.ACQUIRED,status.PROCESSED]).first()
    if current_target is not None:
        return current_target
    current_target = SquareModel.objects.filter(grid_id=grid,status=status.STARTED).first()
    if current_target is not None:
        return current_target
    return AtlasModel.objects.filter(grid_id=grid,status=status.STARTED).first()

def get_target_history(grid: AutoloaderGrid):
    past_targets = get_past_history(grid)
    current_target = get_current_target(grid)
    if current_target is None:
        return past_targets
    return past_targets + [current_target]

def get_target_priority(grid):
    if grid.collection_mode == 'screening' and grid.session_id.microscope_id.vendor != 'JEOL':
        return TargetPriority.HOLE
    return TargetPriority.SQUARE

def get_next_holes(grid: AutoloaderGrid, num_targets: int = 10) -> List[HoleModel]:
    holes = grid.holemodel_set.filter(selected=True).\
        exclude(status__in=[status.SKIPPED, status.STARTED, status.COMPLETED]).\
        order_by('number')[:num_targets]
    return list(holes)

def get_next_squares(grid: AutoloaderGrid, num_targets: int = 10) -> List[SquareModel]:
    squares = grid.squaremodel_set.filter(selected=True).\
        exclude(status__in=[status.SKIPPED, status.STARTED, status.COMPLETED]).\
        order_by('number')[:num_targets]
    return list(squares)

def get_next_targets(grid: AutoloaderGrid, num_targets: int = 10) -> List[Target]:
    targets = []
    target_priority = get_target_priority(grid)
    num_queried = 0
    order = [get_next_holes, get_next_squares]
    if target_priority == TargetPriority.SQUARE:
        order = order[::-1]

    while len(order) > 0:
        targets += order.pop(0)(grid, num_targets)
        num_queried = len(targets)
        num_targets -= num_queried
        if num_targets == 0:
            break

    return targets

@dataclass
class TargetHistory:
    grid_id: str
    past_targets: List[Target] = field(default_factory=list)
    current_target: Target = None
    next_targets: List[Target] = field(default_factory=list)

    past_targets_cache_suffix: str = 'past_targets'
    current_target_cache_suffix: str = 'current_target'
    next_targets_cache_suffix: str = 'next_targets'

    

    @property
    def past_targets_cache_key(self):
        return f'{self.grid_id}_{self.past_targets_cache_suffix}'
    
    @property
    def current_target_cache_key(self):
        return f'{self.grid_id}_{self.current_target_cache_suffix}'
    
    @property 
    def next_targets_cache_key(self):
        return f'{self.grid_id}_{self.next_targets_cache_suffix}'
    
    def get_past_targets(self):
        self.past_targets= get_past_history(self.grid_id)
    
    def get_current_target(self):
        self.current_target= get_current_target(self.grid_id)

    def get_next_targets(self):
        self.next_targets= get_next_targets(self.grid_id)
    
