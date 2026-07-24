import serialem as sem
import math
import json
from pathlib import Path
from typing import Callable
from pydantic import BaseModel
import time
import logging
from .serialem_interface import SerialemInterface, CartridgeLoadingError
from .microscope_interface import Apertures
from .microscope import Microscope

logger = logging.getLogger(__name__)


class JEOLDefaultApertures(Apertures):
    CONDENSER:int=1
    OBJECTIVE:int = 2
    
class JEOLExtraApertures(Apertures):
    CONDENSER:int=0
    CONDENSER_2:int=1
    OBJECTIVE:int = 2
    OBJECTIVE_LOWER:int = 3

class JEOLadditionalSettings(BaseModel):
    transfer_cartridge_path: str = r'C:\Program Data\SerialEM\PyTool\Transfer_Cartridge.bat'


class JEOLmicroscope(Microscope):

    @property
    def atlas_lens_file(self):
        return str(Path(self.scopePath, 'reference', 'atlas_lenses.json'))
    
    @property
    def square_lens_file(self):
        return str(Path(self.scopePath, 'reference', 'square_lenses.json'))
    
    @property
    def medium_mag_lens_file(self): 
        return str(Path(self.scopePath, 'reference', 'medium_mag_lenses.json'))
    
    @property
    def high_mag_lens_file(self):
        return str(Path(self.scopePath, 'reference', 'high_mag_lenses.json'))


class JEOLSerialemInterface(SerialemInterface):
    additional_settings: JEOLadditionalSettings = JEOLadditionalSettings()
    microscope: JEOLmicroscope
    apertures: Apertures = None
    # record_mag: int = 0

    def load_lens_data(self, file:str):
        with open(file, 'r') as f:
            data = json.load(f)
        self.logger.debug(f"Loaded lens data from {file}: {data}")
        for lens, value in data.items():
            self.logger.debug(f"Loading lens data for {lens}: {value}")
            sem.PluginAllDoubles("JEOL", f"SetDec{lens}", *value)

    def save_lens_data(self, file:str):
        data = {}
        for lens in ['GunA1', 'GunA2', 'SpotA', 'CLA1', 'CLA2', 'FLA1', 'FLA2', 'CLs', 'OLs', 'IS1', 'IS2', 'PLA']:
            sem.PluginAllDoubles("JEOL", f"Get{lens}")
            data[lens] = [int(sem.GetVariable("JEOLVal1")), int(sem.GetVariable("JEOLVal2"))]
        with open(file, 'w') as f:
            json.dump(data, f, indent=4)
        
    def checkPump(self, wait=30):
        pass

    def checkDewars(self, wait=30):
        while True:
            if sem.AreDewarsFilling() == 0:
                return
            self.logger.info(f'LN2 is refilling, waiting {wait}s')
            time.sleep(wait)

    def go_to_highmag(self):
        if self.record_mag == 0:
            raise ValueError('Record mag not set. It should be set in the setup method.')
        sem.SetMag(self.record_mag)
        
    def set_atlas_optics(self):
        if self.state.current_mag == 'atlas':
            return
        sem.SetLowDoseMode(1)
        sem.GoToLowDoseArea('R')
        sem.Delay(3, 's')
        sem.SetLowDoseMode(0)
        #Need a round of square mag cycling here
        sem.SetMag(self.atlas_settings.mag)
        # sem.Delay(3, 's')
        sem.SetSlitIn(0)
        sem.SetSpotSize(self.atlas_settings.spotSize)
        sem.SetPercentC2(self.atlas_settings.c2)
        # sem.SetEucentricFocus()
        self.load_lens_data(self.microscope.atlas_lens_file) ##Need to set this up
        sem.ResetDefocus()
        self.state.current_mag = 'atlas'

    def set_square_mag_optics(self):
        if self.state.current_mag == 'square':
            return
        sem.SetLowDoseMode(0)
        sem.SetMag(self.atlas_settings.mag)
        sem.Delay(3, 's')
        sem.SetLowDoseMode(1)
        sem.GoToLowDoseArea('R')
        sem.Delay(3, 's')
        sem.GoToLowDoseArea('S')
        sem.PluginString("JEOL", "SetHexOM", "0000") #FOR ON-free Low Mag
        # sem.ResetDefocus()
        # sem.SetEucentricFocus()
        sem.Delay(3, 's')
        self.load_lens_data(self.microscope.square_lens_file)
        super().set_square_mag_optics()
    
    def set_medium_mag_optics(self):
        if self.state.current_mag == 'medium_mag':
            return
        sem.SetLowDoseMode(1)
        sem.GoToLowDoseArea('R')
        sem.SetEucentricFocus()
        self.load_lens_data(self.microscope.medium_mag_lens_file)
        super().set_medium_mag_optics()


    def set_high_mag_optics(self):
        super().set_high_mag_optics()
        self.load_lens_data(self.microscope.high_mag_lens_file)
        sem.SetEucentricFocus()
        sem.ResetDefocus()

    
    def setup_apertures(self):
        self.apertures = self._apertures_setter()


    def _apertures_setter(self):
        if not self.microscope.apertureControl:
            return None
        extra_apertures_property = int(self.get_property('JeolHasExtraApertures'))
        # self.debug(f'Extra apertures property: {extra_apertures_property}, {type(extra_apertures_property)}')
        if extra_apertures_property == 1:
            logging.info('Extra apertures detected')
            return JEOLExtraApertures
        logging.info('Default apertures detected')
        return JEOLDefaultApertures
  
    def flash_cold_FEG(self, ffDelay:int):
        if not self.microscope.coldFEG or ffDelay < 0:
            return
        self.logger.info('Flashing the cold FEG.')
        sem.LongOperation('FF', str(ffDelay))

    def load_grid(self, position):
        if self.microscope.loaderSize > 1:
            slot_status = sem.ReportSlotStatus(position)

            #This was added to support the new 4.1 2023-02-27 version 
            # that reports the name of the grid along with the position
            if isinstance(slot_status,tuple):
                slot_status = slot_status[1]
            
            if slot_status == -1:
                raise ValueError(f'Slot {position} of the autoloader is empty.')
            if slot_status in [0,2]:
                self.logger.info(f'Autoloader position is occupied')
                self.logger.info(f'Loading grid {position}')
                sem.Delay(5)
                sem.SetColumnOrGunValve(0)
                sem.LoadCartridge(position)
            self.logger.info(f'Grid {position} is loaded')
            sem.Delay(5)
            slot_status = sem.ReportSlotStatus(position)
            #This was added to support the new 4.1 2023-02-27 version 
            # that reports the name of the grid along with the position
            if isinstance(slot_status,tuple):
                slot_status = slot_status[1]
            if  slot_status not in [0,3]:
                raise CartridgeLoadingError('Cartridge did not load properly. Stopping')
        # sem.SetColumnOrGunValve(1)


    def image_shift_by_microns(self,isX,isY,tiltAngle, afis:bool=False, goToRecord=True, delay_multiplier=1, additional_delay=0):
        isX *= -1
        super().image_shift_by_microns(isX,isY,tiltAngle, afis, goToRecord, delay_multiplier, additional_delay)