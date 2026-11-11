from .app import app
import time
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import numpy as np
import logging

logger = logging.getLogger(__name__)


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

@app.task
def process_square_image(square_id: str, square_dir: str, grid_id: str, microscope_id: str):
    from Smartscope.core.grid.run_square import RunSquare
    from Smartscope.core.utils.lock_file import acquire_lock, release_lock, LockError
    from celery.result import allow_join_result

    try:
        lock_path = acquire_lock(square_dir, square_id)
        logger.info(f"Lock file for {square_id} under the path {lock_path}")
    except LockError as e:
        logger.warning(str(e))
        return

    try:
        with allow_join_result():
            RunSquare.process_square_image(square_id, grid_id, microscope_id)
    except Exception as e:
        logger.error(f"Error processing square {square_id}: {e}", exc_info=True)
    finally:
        release_lock(lock_path)


@app.task
def extend_lattice_global(job_id: str, grid_id: str):
    from Smartscope.core.models import AutoloaderGrid
    from Smartscope.core.models import SquareModel
    from Smartscope.lib.Datatypes.grid_geometry import GridGeometry, GridGeometryLevel
    from Smartscope.core.mesh_rotation import calculate_hole_geometry
    from Smartscope.lib.Finders.lattice_extension import lattice_extension
    from Smartscope.lib.image.montage import Montage
    from Smartscope.core.main_commands import add_single_targets, add_holes
    from Smartscope.core.status import status
    
    grid = AutoloaderGrid.objects.get(grid_id=grid_id)

    rotation, spacing = None, None

    geometry = GridGeometry.load(directory=grid.directory)
    rotation, spacing = geometry.get_geometry(level=GridGeometryLevel.SQUARE)
    if any([rotation is None, spacing is None]):
        rotation, spacing = calculate_hole_geometry(grid)


    squares = SquareModel.objects.filter(grid_id=grid, status=status.COMPLETED)
    total_squares = squares.count()
    successful_extensions = 0
    failed_extensions = 0
    failed_items = []
    for i, square in enumerate(squares, start=1):
        send_websocket_progress(
            job_id,
            step=f"{i}/{total_squares}",
            progress=round(i / total_squares * 100),
            message=f"Regrouping BIS and selecting holes in square {square.name}",
            completed=False
        )
        montage = Montage(name=square.name, working_dir=grid.directory)
        montage.read_image()
        targets = square.holemodel_set.all()
        if targets.count() == 0:
            print('No targets found. The square needs at least one target to center the lattice on.')
            failed_extensions += 1
            failed_items.append(square)
            continue
        coords = np.array([t.coords for t in targets])
        new_targets = lattice_extension(coords, montage.image, rotation, spacing)
        add_holes(square.pk, new_targets)
        regroup_bis_and_select.run(job_id, grid_id, square.pk)
        successful_extensions += 1
    
    send_websocket_reload(job_id)
    send_websocket_progress(
        job_id,
        step=f"{total_squares}/{total_squares}",
        progress=100,
        message=f"Lattice extension completed: {successful_extensions} successful, {failed_extensions} failed.",
        completed=True
    )





# ---------------------------------------------------------------------------
# SimSiam clustering: debounced, single-flight, non-blocking.
#
# Every request (one per processed square) stores a fresh token and schedules a task
# `delay` seconds later. When a task fires it only runs if its token is still the latest
# (trailing-edge debounce: the burst has gone quiet) or the oldest unserviced request is
# older than SIMSIAM_CLUSTER_MAX_WAIT_S (so a steady stream of squares can't starve it).
# A cache lock keeps a single clustering per grid/mag_level at a time.
# ---------------------------------------------------------------------------
_SIMSIAM_LOCK_TIMEOUT_S = 2400
_SIMSIAM_LOCK_RETRY_S = 60


def _sim_siam_cluster_keys(grid_id: str, mag_level: str):
    base = f'simsiam_cluster:{grid_id}:{mag_level}'
    return f'{base}:token', f'{base}:first_request', f'{base}:lock'


def request_sim_siam_clustering(grid_id: str, mag_level: str, delay: int = None) -> str:
    from uuid import uuid4
    from django.core.cache import cache
    from .settings import SIMSIAM_CLUSTER_DEBOUNCE_S

    delay = SIMSIAM_CLUSTER_DEBOUNCE_S if delay is None else delay
    token_key, first_key, _ = _sim_siam_cluster_keys(grid_id, mag_level)
    token = uuid4().hex
    cache.set(token_key, token, timeout=None)
    cache.add(first_key, time.time(), timeout=None)  # no-op if an older request is still pending
    sim_siam_cluster_debounced.apply_async(args=[grid_id, mag_level, token], countdown=delay)
    logger.info(f'[grid={grid_id}] SimSiam {mag_level} clustering requested, runs in {delay}s unless superseded')
    return token


@app.task
def sim_siam_cluster_debounced(grid_id: str, mag_level: str, token: str):
    from django.core.cache import cache
    from .settings import SIMSIAM_CLUSTER_MAX_WAIT_S
    from .base_tasks import sim_siam_clustering
    from Smartscope.core.utils.cache_lock import acquire_cache_lock, release_cache_lock
    from celery.result import allow_join_result

    token_key, first_key, lock_key = _sim_siam_cluster_keys(grid_id, mag_level)
    first_request = cache.get(first_key)
    if first_request is None:
        return 'already serviced'
    overdue = (time.time() - first_request) >= SIMSIAM_CLUSTER_MAX_WAIT_S
    if cache.get(token_key) != token and not overdue:
        return 'superseded'
    lock_token = acquire_cache_lock(lock_key, ttl=_SIMSIAM_LOCK_TIMEOUT_S)
    if lock_token is None:
        # Another clustering is running; it snapshotted embeddings before our request may have
        # landed, so try again later instead of dropping it.
        sim_siam_cluster_debounced.apply_async(args=[grid_id, mag_level, token], countdown=_SIMSIAM_LOCK_RETRY_S)
        return 'locked, retrying'
    try:
        # Clear before snapshotting the embeddings so requests arriving mid-run schedule a new run.
        cache.delete(first_key)
        with allow_join_result():  # we wait on the microservice task's result from inside a task
            sim_siam_clustering(mag_level=mag_level, grid_id=grid_id)
        return 'clustered'
    except Exception:
        logger.exception(f'[grid={grid_id}] SimSiam {mag_level} clustering failed')
        raise
    finally:
        release_cache_lock(lock_key, lock_token)
