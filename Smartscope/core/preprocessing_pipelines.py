import os
import logging
from pathlib import Path
import asyncio

from Smartscope.core.models.grid import AutoloaderGrid
from Smartscope.core.settings.worker import DEFAULT_PREPROCESSING_PIPELINE, NEXTPYP_PREPROCESSING_PIPELINE  
from Smartscope.lib.logger import add_log_handlers


logger = logging.getLogger(__name__)

from .pipelines import PreprocessingPipelineCmd, SmartscopePreprocessingPipeline, CryoSPARCPipeline, NextPYPPreprocessingPipeline, NextPYPPreprocessingCmdKwargs


PREPROCESSING_PIPELINE_FACTORY = {
    "smartscopePipeline" : SmartscopePreprocessingPipeline,
    # "cryoSPARC" : CryoSPARCPipeline,
    "nextpypPipeline" : NextPYPPreprocessingPipeline,
}

def load_preprocessing_pipeline(file:Path):
    if file.exists():
        return PreprocessingPipelineCmd.parse_file(file)
    logger.info(f'Preprocessing file {file} does not exist. Loading default pipeline.')
    # for default in DEFAULT_PREPROCESSING_PIPELINE:
    #     if default.exists():
    #         return PreprocessingPipelineCmd.parse_file(default)
    for nextpyp in NEXTPYP_PREPROCESSING_PIPELINE:
        if nextpyp.exists():
            logger.info(f'Loading nextPYP preprocessing pipeline from {nextpyp}.')
            return NextPYPPreprocessingCmdKwargs.parse_file(nextpyp)
    logger.info(f'nextPYP preprocessing pipeline not found.')
    return None 
    

def highmag_processing(grid_id: str, *args, **kwargs) -> None:
    try:
        grid = AutoloaderGrid.objects.get(grid_id=grid_id)
        os.chdir(grid.directory)
        add_log_handlers(directory=grid.session_id.directory, name='proc.out')
        logger.debug(f'Log handlers:{logger.handlers}')
        preprocess_file = Path('preprocessing.json')
        cmd_data = load_preprocessing_pipeline(preprocess_file)
        if cmd_data is None:
            logger.info('Trying to load preprocessing parameters from command line arguments.')
            cmd_data = PreprocessingPipelineCmd.model_validate(**kwargs)
        if cmd_data.is_running():
            logger.info(f'Processings with PID:{cmd_data.process_pid} seem to already be running, '+ \
                'please kill the other one before continuing.')
            return
        cmd_data.process_pid=os.getpid()
        preprocess_file.write_text(cmd_data.model_dump_json())
        pipeline = PREPROCESSING_PIPELINE_FACTORY[cmd_data.pipeline](grid, cmd_data.kwargs)
        pipeline.start()
    except Exception as e:
        logger.exception(e)
    except KeyboardInterrupt as e:
        logger.info('SIGINT recieved by the highmag_processing.')
    finally:
        logger.debug('Wrapping up')
        if 'pipeline' in locals():
            pipeline.stop()
