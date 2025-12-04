
from typing import Union
from pathlib import Path
from pydantic import BaseModel, Field, validator
import logging
logger = logging.getLogger(__name__)


class NextPYPPreprocessingCmdKwargs(BaseModel):
    pixel_size:float = 1.0
    frames_directory:str = ""
    n_processes:int = 1
    path_to_token:str = "/root/nextpyp_token"
    nextpyp_userid:str = ""