
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
    
    # For accessing sessions
    url_base:str = ""
    
    # Dataset settings
    gain_reference:str = ""
    gain_flipv:bool = True
    
    # Microscope settings
    scope_pixel:float = 1.0
    scope_voltage:int = 300
    scope_cs:float = 2.7
    
    # File transfer settings
    stream_transfer_operation:str = "link"
    stream_transfer_restart:bool = True
    
    # Particle picking settings
    detect_rad:float = 65.0
    detect_method:str = "all"
    detect_dist:int = 40
    
    # 2D Classification settings
    class2d_num:int = 50
    class2d_box:int = 96
    class2d_bin:int = 4
    
    # SLURM settings
    slurm_verbose:bool = True
    slurm_tasks:int = 7
    slurm_memory:int = 14
    slurm_daemon_walltime:str = "0-01:00:00"
    