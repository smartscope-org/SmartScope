from .app import app
import time
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_websocket_progress(job_id: str, step: int, progress: int, message: str, completed: bool):
    channel_layer = get_channel_layer()
    group_name = f"job_{job_id}"

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "progress.update",
            "step": step,
            "progress": progress,
            "message": message,
            "completed": completed
        }
    )

def send_websocket_reload(job_id: str):
    channel_layer = get_channel_layer()
    group_name = f"job_{job_id}"

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "progress.reload"
        }
    )

@app.task
def test_long_running_task(job_id: str):
    channel_layer = get_channel_layer()
    group_name = f"job_{job_id}"

    total_steps = 4
    for i in range(1, total_steps + 1):
        time.sleep(3)  # simulate work
        send_websocket_progress(
            job_id,
            step=i,
            progress=round(i / total_steps * 100),
            message=f"Progress {i}",
            completed=False if i < total_steps else True
        )

    return "Done"


@app.task
def regroup_bis_and_select(job_id: str, grid_id: str, square_id: str = 'all'):
    from Smartscope.core.models import AutoloaderGrid
    from Smartscope.core.main_commands import select_areas, reset_hole_selection
    from Smartscope.core.db_manipulations import group_holes_from_square_for_BIS

    send_websocket_progress(
        job_id,
        step=f"0",
        progress=0,
        message=f"Removing all previous hole selections",
        completed=False
    )    
    squares = reset_hole_selection(grid_id, square_id)
    grid = AutoloaderGrid.objects.get(grid_id=grid_id)

    collection_params = grid.params_id

    total_squares = len(squares)
    for i, square in enumerate(squares, start=1):
        send_websocket_progress(
            job_id,
            step=f"{i}/{total_squares}",
            progress=round(i / total_squares * 100),
            message=f"Regrouping BIS and selecting holes in square {square.name}",
            completed=False
        )
        group_holes_from_square_for_BIS(square,
                                        max_radius=collection_params.bis_max_distance,
                                        min_group_size=collection_params.min_bis_group_size)
        select_areas('square', square.pk, collection_params.holes_per_square)
    send_websocket_reload(job_id)
    send_websocket_progress(
        job_id,
        step=f"{total_squares}/{total_squares}",
        progress=100,
        message="Regrouping and selection completed",
        completed=True
    )
