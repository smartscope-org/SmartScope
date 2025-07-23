from Smartscope.bin import smartscope
from ..models import AutoloaderGrid
from ..target_history import get_past_history, get_current_target, get_next_targets, TargetHistory

grid_id = AutoloaderGrid.objects.get(pk="1grid_1zLfEEH9CUtt6Y25vpT6r3K5")

def test_get_past_history():
    history = get_past_history(grid_id, 10)
    print(history)
    assert len(history) == 7

def test_get_current_target():
    current_target = get_current_target(grid_id)
    print(f'Current target: {current_target}')
    assert current_target is not None

def test_get_next_targets():
    next_targets = get_next_targets(grid_id, 10)
    print(f'Next targets: {next_targets}')
    assert len(next_targets) == 2
