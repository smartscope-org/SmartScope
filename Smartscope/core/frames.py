import os
from pathlib import Path
import yaml
import re
import logging
from pydantic import BaseModel
from Smartscope.core.models import AutoloaderGrid
from Smartscope.core.settings.worker import SMARTSCOPE_CUSTOM_CONFIG

logger = logging.getLogger(__name__)


class FramesConfig(BaseModel):
    frames_directory_structure: list[str] = ['{{session_id.working_directory}}', '{{position}}_{{name}}']


def get_frames_config(grid:AutoloaderGrid):
    detector = grid.parent.detector_id
    custom_paths = SMARTSCOPE_CUSTOM_CONFIG / 'custom_paths.yaml'
    if not custom_paths.exists():
        logger.debug(f'No custom paths file found at {custom_paths}')
        return None
    file = yaml.safe_load(custom_paths.read_text())
    
    key = f'detector_id_{detector.pk}'
    paths = file.get(key, None)
    if paths is None:
        logger.debug(f'No key {key} file found at {custom_paths}')
        return None
    return FramesConfig.model_validate(paths)


def parse_string(prefix:str, grid:AutoloaderGrid):
    pattern = r'(\{\{[^}]+\}\})'
    matches = re.findall(pattern, prefix)
    for match in matches:
        clean_match = match.replace('{{', '').replace('}}', '')
        split = clean_match.split('.')
        x = grid
        for s in split:
            x = getattr(x, s)
        logger.debug(f'Parsed {match} to {x}')
        prefix = prefix.replace(match,str(x))
    return prefix

def generate_frames_dir(grid:AutoloaderGrid, full_path:bool=False) -> Path:
    config = get_frames_config(grid)
    if config is None:
        logger.debug('No custom frames config found, using default structure')
        config = FramesConfig()
    print(config)
    path_parts = []
    for part in config.frames_directory_structure:
        parsed_part = parse_string(part, grid)
        path_parts.append(parsed_part)

    path = Path(*path_parts)
    if 'Falcon' in grid.session_id.detector_id.detector_model:
        logger.debug('Settings frames directory for Falcon detectors')
        path = Path('_'.join(path_parts))

    if full_path:
        return Path(grid.parent.working_directory, path)
    return path