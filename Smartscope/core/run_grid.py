import os
import sys
import time
import logging
import numpy as np
from scipy.spatial.distance import cdist
from typing import Union
from pathlib import Path
from django.utils import timezone
from django.conf import settings
from django.db import transaction

from Smartscope.lib.image_manipulations import auto_contrast_triangle_cdf, export_as_png
from Smartscope.sim_siam.plugin import SimSiamEmbedding
from Smartscope.tasks.long_actions_tasks import process_square_image as process_square_image_task

from .grid.grid_status import GridStatus
from .grid.finders import find_targets
from .grid.grid_io import GridIO
from .grid.run_io import get_file_and_process
from .grid.run_hole import RunHole
from .interfaces.microscope_interface import MicroscopeInterface
from .selectors import selector_wrapper
from .models import SquareModel, AutoloaderGrid
from .settings.worker import PROTOCOL_COMMANDS_FACTORY
from .status import status
from .protocols import get_or_set_protocol
from .preprocessing_pipelines import load_preprocessing_pipeline
from .db_manipulations import update, queue_atlas, add_targets
from .selection.strategies import TARGET_SELECTION_STRATEGIES
from .navigation import get_queue, get_target_priority, NAVIGATION_STRATEGIES, TargetPriority
from .stats import count_completed

logger = logging.getLogger(__name__)

def run_grid(
        grid:AutoloaderGrid,
        scope:MicroscopeInterface,
        screening_mode: bool = False,
        skip_loading: bool = False

    ): 
    """Main logic for the SmartScope process
    Args:
        grid (AutoloaderGrid): AutoloadGrid object from Smartscope.server.models
        session (ScreeningSession): ScreeningSession object from Smartscope.server.models
    """
    logger.info(f'###Check status of grid, grid ID={grid.grid_id}.')
    session = grid.session_id
    session_id = session.pk
    microscope = session.microscope_id


    grid = update(grid, refresh_from_db=True, last_update=None)
    update.grid = grid

    if grid.status == GridStatus.COMPLETED:
        logger.info(f'Grid {grid.name} already complete. grid ID={grid.grid_id}')
        return
    
    if grid.status == GridStatus.ABORTING:
        logger.info(f'Aborting {grid.name}')
        update(grid, status=GridStatus.COMPLETED)
        return

    logger.info(f'Starting {grid.name}, status={grid.status}') 
    if grid.status is GridStatus.NULL:
        grid = update(grid, status=GridStatus.STARTED, start_time=timezone.now())
    else:
        grid = update(grid, status=GridStatus.STARTED)

    GridIO.create_grid_directories(grid.directory)
    logger.info(f"Create and then enter into Grid directory={grid.directory}")
    os.chdir(grid.directory)
    params = grid.params_id

    protocol = get_or_set_protocol(grid)
    preprocessing = load_preprocessing_pipeline(Path('preprocessing.json'))
    preprocessing.start(grid)
    check_stop_flag(session_id)
    atlas = queue_atlas(grid)

    # scope
    runScopeProtocolSteps(
        scope,
        protocol.preImaging.steps,
        params,
        grid
    )
    update(grid, loading_time=timezone.now())
    check_stop_flag(session_id)

    needs_reregistations = grid.unloading_time is not None and grid.loading_time > grid.unloading_time
    if needs_reregistations:
        logger.info('NOT IMPLEMENTED YET. Re-registering grid after re-loading')
        # reregister_grid(scope, grid, protocol)

    SELECTION_STRATEGY = TARGET_SELECTION_STRATEGIES['original']
    NAVIGATION_STRATEGY = NAVIGATION_STRATEGIES['original']
    # run acquisition
    if atlas.status == status.QUEUED or atlas.status == status.STARTED:
        atlas = update(atlas, status=status.STARTED)
        logger.info('Waiting on atlas file')
        runScopeProtocolSteps(
            scope,
            protocol.atlas.steps,
            params,
            atlas
        )
        atlas = update(atlas,
            status=status.ACQUIRED,
            completion_time=timezone.now()
        )

    # find targets
    if atlas.status == status.ACQUIRED:
        logger.info('Atlas acquired')
        montage = get_file_and_process(
            raw=atlas.raw,
            name=atlas.name,
            directory=microscope.scope_path
        )
        export_as_png(montage.image, montage.png, normalization=auto_contrast_triangle_cdf)
        targets, finder_method, classifier_method, _ = find_targets(
            montage,
            protocol.atlas.targets.finders
        )
        add_targets(
            grid,
            atlas,
            targets,
            SquareModel,
            finder_method,
            classifier_method
        )
        atlas = update(atlas,
            status=status.PROCESSED,
            pixel_size=montage.pixel_size,
            shape_x=montage.shape_x,
            shape_y=montage.shape_y,
            stage_z=montage.stage_z
        )
    
    # 
    if atlas.status == status.PROCESSED:
        if not 'montage' in locals():
            from Smartscope.lib.image.montage import Montage
            montage = Montage(name=atlas.name)
            montage.load_or_process()
        selector_wrapper(protocol.atlas.targets.selectors, atlas, montage=montage)
        SimSiamEmbedding().run(mag_level='square', grid_id=grid.grid_id)
        selection_strategy = SELECTION_STRATEGY(n_targets=params.squares_num)
        selected = selection_strategy.select(atlas)
        print(f'Selected {len(selected)} targets from atlas')
        with transaction.atomic():
            for obj,priority in zip(*selected):
                update(obj, selected=True, status='queued', acquisition_priority=priority)
        atlas = update(atlas, status=status.COMPLETED)

        #Release atlas items from memory.
        if 'montage' in locals():
            del montage
        del atlas
    logger.info('Atlas analysis is complete')
    screening_mode = bool(str(screening_mode).strip().lower() in ['true', '1'])

    if screening_mode:
        logger.info('Screening mode: Atlas only - stopping execution after atlas analysis.')
        update(grid, status=GridStatus.COMPLETED)
        return 'finished'

    # Crash recovery: re-dispatch processing tasks for squares left in ACQUIRED
    # state from a previous interrupted run.
    for sq in grid.squaremodel_set.filter(status__in=[status.ACQUIRED,status.QUEUED_FOR_PROCESSING]):
        logger.info(f'Re-dispatching processing task for previously acquired square {sq}')
        process_square_image_task.delay(sq.square_id, grid.grid_id, microscope.microscope_id)
        if sq.status != status.QUEUED_FOR_PROCESSING:
            update(sq, status=status.QUEUED_FOR_PROCESSING)

    running = True
    is_done = False
    while running:
        check_stop_flag(session_id)
        grid = update(grid, refresh_from_db=True, last_update=None)
        params = grid.params_id
        if params.max_exposures_for_grid > 0 and count_completed(grid) >= params.max_exposures_for_grid:
            running = False
            continue
        if grid.status == GridStatus.ABORTING:
            running = False
            continue

        priority = get_target_priority(grid, SELECTION_STRATEGY.target_priority)
        queue, priority  = get_queue(grid, priority, NAVIGATION_STRATEGY)

        
        logger.info(f'Targets done: {is_done}')
        if priority == TargetPriority.HOLE:
            hole = queue[0]
            is_done = False
            logger.info(f'Running Hole {hole}')
            # process medium image
            hole = update(hole, status=status.STARTED)
            runScopeProtocolSteps(
                scope,
                protocol.mediumMag.steps,
                params,
                hole
            )
            if hole.status == status.SKIPPED:
                continue
            hole = update(hole,
                status=status.ACQUIRED,
                completion_time=timezone.now()
            )
            RunHole.process_hole_image(hole, grid, microscope)
            if hole.status == status.SKIPPED:
                continue


            for hm in hole.targets.exclude(status__in=[status.ACQUIRED,status.COMPLETED]).order_by('hole_id__number'):
                hm = update(hm, refresh_from_db=False, status=status.STARTED)
                if hm.hole_id.status == status.SKIPPED:
                    break
                hm = runScopeProtocolSteps(
                    scope,
                    protocol.highMag.steps,
                    params,
                    hm
                )
                hm = update(hm,
                    status=status.ACQUIRED,
                    completion_time=timezone.now(),
                    extra_fields=['is_x','is_y','offset','frames']
                )
                if hm.hole_id.bis_type != 'center':
                    update(hm.hole_id, status=status.ACQUIRED, completion_time=timezone.now())
            update(hole, status=status.COMPLETED)
            runScopeProtocolSteps(
                scope,
                protocol.postHighMag.steps,
                params,
                hole
            )
        elif priority == TargetPriority.SQUARE:
            is_done = False
            square = queue[0]
            logger.info(f'Running Square {square}')
            # process square
            if square.status == status.QUEUED or square.status == status.STARTED:
                square = update(square, status=status.STARTED)
                logger.info('Waiting on square file')
                runScopeProtocolSteps(
                    scope,
                    protocol.square.steps,
                    params,
                    square
                )
                square = update(square, status=status.ACQUIRED, completion_time=timezone.now())
            process_square_image_task.delay(square.square_id, grid.grid_id, microscope.microscope_id)
            square = update(square, status=status.QUEUED_FOR_PROCESSING)
        elif is_done:
            microscope_id = microscope.pk
            tmp_file = os.path.join(settings.TEMPDIR, f'.pause_{microscope_id}')
            if os.path.isfile(tmp_file) or scope.microscope.loaderSize == 1:
                paused = os.path.join(settings.TEMPDIR, f'paused_{microscope_id}')
                open(paused, 'w').close()
                update(grid, status=GridStatus.PAUSED)
                logger.info('SerialEM is paused')
                while os.path.isfile(paused):
                    sys.stdout.flush()
                    time.sleep(3)
                next_file = os.path.join(settings.TEMPDIR, f'next_{microscope_id}')
                if os.path.isfile(next_file):
                    os.remove(next_file)
                    running = False
                else:
                    update(grid, status=GridStatus.STARTED)
            else:
                running = False
        else:
            in_flight_statuses = [
                status.ACQUIRED,
                status.QUEUED_FOR_PROCESSING,
                status.PROCESSED,
                status.TARGETS_SELECTED,
                status.GROUPED,
                status.TARGETS_PICKED,
            ]
            if grid.squaremodel_set.filter(status__in=in_flight_statuses).exists():
                logger.info('Waiting for square processing tasks to complete...')
                time.sleep(3)
            else:
                logger.debug('All processes complete')
                is_done = True
        logger.debug(f'Running: {running}')
    else:
        update(grid, status=GridStatus.COMPLETED)
        logger.info('Grid finished')
        scope.unload_grid()
        update(grid, unloading_time=timezone.now())
        return 'finished'

# class TargetPriority(Enum):
    # HOLE = 'hole'
    # SQUARE = 'square'


# def get_target_priority(grid, queue):
#     square, hole = queue
#     if hole is None and square is None:
#         return
#     if hole is None:
#         return TargetPriority.SQUARE
#     if square is None:
#         return TargetPriority.HOLE
#     if grid.collection_mode == 'screening' and grid.session_id.microscope_id.vendor != 'JEOL':
#         return TargetPriority.HOLE
#     return TargetPriority.SQUARE

# def get_queue(grid):
#     square = grid.squaremodel_set.filter(selected=True).\
#         exclude(status__in=[status.SKIPPED, status.COMPLETED]).\
#         order_by('number').first()
#     hole = grid.holemodel_set.filter(selected=True, square_id__status=status.COMPLETED).\
#         exclude(status__in=[status.SKIPPED, status.COMPLETED]).\
#         order_by('square_id__completion_time', 'number').first()
#     return square, hole#[h for h in holes if not h.bisgroup_acquired]

def get_stop_file(session_id: str, default=None) -> Union[Path,None]:
    stop_file = Path(settings.TEMPDIR, f'{session_id}.stop')
    if stop_file.exists():
        logger.debug(f'Stop file {stop_file} found.')
        return stop_file
    return default

def clear_stop_file(session_id: str) -> bool:
    stop_file = get_stop_file(session_id)
    if stop_file is None:
        return False
    stop_file.unlink()
    return True

def check_stop_flag(session_id: str):
    if clear_stop_file(session_id):
        raise KeyboardInterrupt()


def parse_method(method):
    if not isinstance(method, dict):
        logger.info(f'Running protocol method: {method}')
        return method, {}, [], {}
    args = []
    kwargs = dict()
    method_name, content = next(iter(method.items()))
    kwargs = content.get('kwargs', {})
    args = content.get('args', [])

    logger.info(f'Running protocol method: {method_name}, {content} with args={args} and kwargs={kwargs}')
    return method_name, content, args, kwargs
    

def runScopeProtocolSteps(
        scope,
        methods,
        params,
        instance,
    ):
    for method in methods:
        method, content, args, kwargs = parse_method(method)
        output = PROTOCOL_COMMANDS_FACTORY[method](scope,params,instance, content, *args, **kwargs)
        if output is not None:
            instance = output
    return output

def reregister_grid(scope, grid, protocol):
    logger.info('Re-registering grid')
    completed_squares = list(grid.squaremodel_set.filter(status=status.COMPLETED))
    if len(completed_squares) < 2:
        logger.info('Not enough completed squares to re-register grid')
        return
    coords = []
    for square in completed_squares:
        coordinates = square.finders.first()
        coords.append((coordinates.stage_x, coordinates.stage_y))

    coords_np = np.asarray(coordinates, dtype=float)
    # use scipy cdist to compute pairwise distances
    D = cdist(coords_np, coords_np, metric='euclidean')

    i, j = np.unravel_index(int(np.argmax(D)), D.shape)
    maxd = float(D[i, j])
    pair = (completed_squares[i], completed_squares[j])

    logger.info(f'Farthest squares: {pair[0]} and {pair[1]}, distance={maxd}')

    old_positions = []
    new_positions = []
    for square in pair:
        new_positions.append(PROTOCOL_COMMANDS_FACTORY['reregister_square'](scope, grid.params_id, square))    
        old_positions.append(square.stage_coords)
    
    # Compute rotation and translation
    old_positions = np.array(old_positions)
    new_positions = np.array(new_positions)
    
    