
import os
import sys
import logging

from django.db import close_old_connections

logger = logging.getLogger(__name__)


from .interfaces.microscope import Detector, AtlasSettings
from .interfaces.microscope_methods import select_microscope_interface
from .models import ScreeningSession, Process
from .grid.grid_status import GridStatus
from .db_manipulations import update
from .run_grid import run_grid, clear_stop_file

from Smartscope.lib.logger import add_log_handlers

def autoscreen(session_id:str, screening_mode: bool=False, skip_loading: bool=False):
    '''
    major procedure: autoscreen
    '''
    session = ScreeningSession.objects.get(session_id=session_id)
    microscope_model = session.microscope_id
    add_log_handlers(directory=session.directory, name='run.out')
    logger.debug(f'Main Log handlers:{logger.handlers}')
    process = create_process(session)
    clear_stop_file(session.session_id)
    if microscope_model.isLocked:
        logger.warning(f"""
            The requested microscope is busy.
            Lock file {microscope_model.lockFile} found
            Session id: {session} is currently running.
            If you are sure that the microscope is not running,
            remove the lock file and restart.
            Exiting.
        """)
        sys.exit(0)
    write_sessionLock(session, microscope_model.lockFile)

    try:
        # grids = list(session.autoloadergrid_set.all().order_by('position'))
        logger.info(f'Process: {process}')
        logger.info(f'Session: {session}')
        # logger.info(f"Grids: {', '.join([grid.__str__() for grid in grids])}")
        scopeInterface, microscope, additional_settings = select_microscope_interface(microscope_model)


        with scopeInterface(
                microscope = microscope.model_validate(session.microscope_id),
                detector= Detector.model_validate(session.detector_id) ,
                atlas_settings= AtlasSettings.model_validate(session.detector_id),
                additional_settings=additional_settings
            ) as scope:

            logger.debug(f'Main Log handlers:{logger.handlers}')
            logger.debug(scope.__dict__)
            logger.debug(scope.microscope.__dict__)
            # RUN grid
            while True:
                grids = list(session.autoloadergrid_set.all().order_by('position'))
                grid = next(filter(lambda g: g.status not in [GridStatus.COMPLETED], grids), None)
                if grid is None:
                    break
                status = run_grid(grid, scope, screening_mode=screening_mode) #processing_queue,
            status = 'complete'
    except Exception as e:
        logger.exception(e)
        status = 'error'
        if 'grid' in locals():
            update.grid = grid
            close_old_connections()
            update(grid, status=GridStatus.ERROR)
    except KeyboardInterrupt:
        logger.info('Stopping Smartscope.py autoscreen')
        status = 'killed'
    finally:
        os.remove(microscope_model.lockFile)
        close_old_connections()
        update(process, status=status)
        logger.info('Done.')


def create_process(session):
    process = session.process_set.first()

    if process is None:
        process = Process(session_id=session, PID=os.getpid(), status='running')
        process = process.save()
        return process

    return update(process, PID=os.getpid(), status='running')


def write_sessionLock(session, lockFile):
    with open(lockFile, 'w') as f:
        f.write(session.session_id)


def run_protocol_command(grid_id:str, command:str):
    from Smartscope.core.models import AutoloaderGrid
    from Smartscope.core.settings.worker import PROTOCOL_COMMANDS_FACTORY
    grid = AutoloaderGrid.objects.get(pk=grid_id)
    session = grid.session_id
    microscope_model = session.microscope_id
    params = grid.params_id
    add_log_handlers(directory=session.directory, name='run.out')
    logger.debug(f'Main Log handlers:{logger.handlers}')
    clear_stop_file(session.session_id)
    if microscope_model.isLocked:
        logger.warning(f"""
            The requested microscope is busy.
            Lock file {microscope_model.lockFile} found
            Session id: {session} is currently running.
            If you are sure that the microscope is not running,
            remove the lock file and restart.
            Exiting.
        """)
        sys.exit(0)
    write_sessionLock(session, microscope_model.lockFile)

    try:
        scopeInterface, microscope, additional_settings = select_microscope_interface(microscope_model)


        with scopeInterface(
                microscope = microscope.model_validate(session.microscope_id),
                detector= Detector.model_validate(session.detector_id) ,
                atlas_settings= AtlasSettings.model_validate(session.detector_id),
                additional_settings=additional_settings,
                close_valves_on_disconnect=False
            ) as scope:
            logger.info(f'Running protocol command {command} on grid {grid}')
            scope.setup_apertures()
            PROTOCOL_COMMANDS_FACTORY[command](scope,params,instance=None,content={})

    except Exception as e:
        logger.exception(e)
        if 'grid' in locals():
            update.grid = grid
            update(grid, status=GridStatus.ERROR)
    except KeyboardInterrupt:
        logger.info('Stopping Smartscope.py run_prototol_command')
    finally:
        os.remove(microscope_model.lockFile)


