import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Tuple

import serialem as sem

from .microscope import AtlasSettings, Detector, Microscope, MicroscopeState

logger = logging.getLogger(__name__)


class Apertures(ABC):
    pass


class MicroscopeLogger:
    prefix = "MicroscopeInterface"
    debug_prefix = "DEBUG:"
    info_prefix = "INFO:"
    error_prefix = "ERROR"

    def _create_message(self, message: str, *prefix: str):
        return " ".join(prefix) + message

    def info(self, message: str):
        msg = self._create_message(message, self.prefix, self.info_prefix)
        logger.info(msg)

    def debug(self, message: str):
        msg = self._create_message(message, self.prefix, self.debug_prefix)
        logger.debug(msg)

    def error(self, message: str):
        msg = self._create_message(message, self.prefix, self.debug_prefix)
        logger.error(msg)


@dataclass
class MicroscopeInterface(ABC):
    logger = MicroscopeLogger()
    microscope: Microscope
    detector: Detector
    atlas_settings: AtlasSettings
    state: MicroscopeState = field(default_factory=MicroscopeState)
    apertures: Apertures = None
    additional_settings: dict = None
    has_hole_ref: bool = False
    hole_crop_size: int = 0
    focus_position_set: bool = False
    close_valves_on_disconnect: bool = True

    def __enter__(self):
        logger.debug(f"Additional settings set: {self.additional_settings}")
        self.connect()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.disconnect()

    def reset_image_shift_values(self, afis: bool = False, save_beam_tilt: bool = True):
        self.state.reset_image_shift_values()

    @abstractmethod
    def reset_stage(self):
        pass

    @abstractmethod
    def remove_slit(self):
        pass

    @abstractmethod
    def eucentricity_by_focus(self):
        pass

    @abstractmethod
    def eucentric_height_after_distance(self, tilt_to:int=10, increments:int=-5, max_movement:int=200, distance_threshold:int=400):
        pass

    @abstractmethod
    def call(self, script):
        pass

    @abstractmethod
    def call_function(self, function, *args):
        pass

    @abstractmethod
    def checkDewars(self, wait=30) -> None:
        pass

    @abstractmethod
    def checkPump(self, wait=30):
        pass

    def flash_cold_FEG(self, ffDelay: int):
        pass

    def recenter_beam(self, interval_in_minutes: int = 5):
        pass

    def _rollDefocus(self, def1, def2, step):
        mindef = max([def1, def2])
        maxdef = min([def1, def2])
        defocusTarget = round(sem.ReportTargetDefocus() - abs(step), 2)
        if defocusTarget < maxdef or defocusTarget > mindef:
            defocusTarget = mindef
        self.state.defocusTarget = defocusTarget
        return defocusTarget

    def roll_defocus(self, def1, def2, step):
        pass

    def setup_serialem(self):
        pass

    def reset_state(self):
        self.has_hole_ref = False
        self.focus_position_set = False

    @abstractmethod
    def report_stage(self):
        return 0, 0, 0

    @abstractmethod
    def eucentricHeight(self, tiltTo: int = 10, increments: int = -5) -> float:
        pass

    @abstractmethod
    def tiltTo(self, angle):
        pass

    @abstractmethod
    def eucentricity():
        pass

    @abstractmethod
    def get_image_settings(self, *args, **kwargs):
        pass

    @abstractmethod
    def buffer_to_numpy():
        pass

    @abstractmethod
    def numpy_to_buffer():
        pass

    @abstractmethod
    def set_atlas_optics(self):
        pass

    @abstractmethod
    def set_atlas_optics_delay(self, delay=10):
        pass

    @abstractmethod
    def set_atlas_optics_imaging_state(self, state_name="Atlas"):
        pass

    @abstractmethod
    def set_square_mag_optics(self):
        pass

    @abstractmethod
    def set_medium_mag_optics(self):
        pass

    @abstractmethod
    def set_high_mag_optics(self):
        pass

    @abstractmethod
    def atlas(self, size, file=""):
        pass

    @abstractmethod
    def atlas_in_low_dose_search(self, size, file=""):
        pass

    @abstractmethod
    def realign_to_square(self):
        return 0, 0, 0

    @abstractmethod
    def square(self, file=""):
        pass

    @abstractmethod
    def align_to_hole_ref(self):
        return 0, 0

    @abstractmethod
    def reset_image_shift(self):
        pass

    @abstractmethod
    def align_to_coord(self, coord):
        pass

    @abstractmethod
    def moveStage(self, stage_x, stage_y, stage_z):
        pass

    @abstractmethod
    def acquire_medium_mag(self):
        pass

    @abstractmethod
    def medium_mag_hole(self, file: str = ""):
        pass

    @abstractmethod
    def load_hole_ref(self):
        pass

    @abstractmethod
    def image_shift_by_microns(
        self,
        isX,
        isY,
        tiltAngle,
        afis: bool = False,
        goToRecord=True,
        delay_multiplier=1,
        additional_delay=0,
    ):
        pass

    @abstractmethod
    def set_focus_for_bis_tilt(self, isY, tiltAngle):
        pass

    @abstractmethod
    def zero_image_shift(self):
        pass

    @abstractmethod
    def get_mag_area_in_microns(self, magSet="V") -> Tuple:
        pass

    @abstractmethod
    def medium_mag_montage(self, size, file=""):
        pass

    @abstractmethod
    def highmag(
        self, isXi, isYi, isX, isY, currentDefocus, tiltAngle, file="", frames=True
    ):
        pass

    @abstractmethod
    def connect(self, directory: str):
        pass

    @abstractmethod
    def setFocusPosition(self, distance, angle):
        pass

    @abstractmethod
    def setup(self, saveframes: bool, frames_dir: str = "", framesName=None):
        pass

    @abstractmethod
    def disconnect(self, close_valves=True):
        pass

    @abstractmethod
    def load_grid(self, position):
        pass

    def unload_grid(self):
        pass

    def refineZLP(self, zerolossDelay):
        pass

    def collectHardwareDark(self, harwareDarkDelay: int):
        pass

    def reset_AFIS_image_shift(self, afis: bool = False):
        pass

    def save_eucentric_focus(self):
        pass

    @abstractmethod
    def open_valves(self):
        pass

    @abstractmethod
    def autofocus(self, def1, def2, step):
        pass

    @abstractmethod
    def wait_drift(self, driftTarget):
        pass

    @abstractmethod
    def autofocus_after_distance(self, def1, def2, step, distance):
        pass

    @abstractmethod
    def report_aperture_size(self, aperture: int):
        pass

    @abstractmethod
    def remove_aperture(self, aperture: int, wait: int = 10):
        pass

    @abstractmethod
    def insert_aperture(self, aperture: int, aperture_size: int, wait: int = 10):
        pass

    @abstractmethod
    def set_apertures_for_high_mag(
        self, condenser_aperture_size: int, objective_aperture_size: int
    ):
        pass

    @abstractmethod
    def set_apertures_for_lowmag(self):
        pass

    @abstractmethod
    def set_apertures_for_square_mag(self):
        pass

    @abstractmethod
    def set_apertures_for_medium_mag(
        self, condenser_aperture_size: int, objective_aperture_size: int
    ):
        pass

    def set_highmag_counting_mode(self):
        pass
