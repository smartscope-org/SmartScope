from pathlib import PureWindowsPath
from typing import Tuple
import serialem as sem
import time
import logging
import math
import numpy as np
from .microscope import CartridgeLoadingError
from .microscope_interface import MicroscopeInterface, MicroscopeLogger
from Smartscope.lib.Finders.basic_finders import find_square

logger = logging.getLogger(__name__)


class SerialEMLogger(MicroscopeLogger):

    def info(self, message:str):
        msg = self._create_message(message, self.prefix, self.info_prefix)
        logger.info(msg)
        sem.Echo(msg)
    
    def debug(self, message: str):
        msg = self._create_message(message, self.prefix, self.debug_prefix)
        logger.debug(msg)
        sem.Echo(msg)
    
    def error(self, message: str):
        msg = self._create_message(message, self.prefix, self.error_prefix)
        logger.debug(msg)
        sem.Echo(msg)

class SerialemInterface(MicroscopeInterface):
    logger = SerialEMLogger()

    def eucentricHeight(self, tilt_to:int=10, increments:int=-5, max_movement:int=200):
        binning = sem.ReportBinning('S')
        self.logger.info(f'Doing eucentric height, setting Search binning to 4.')
        sem.SetBinning('S', 4)
        offsetZ = 51
        iteration = 0
        while abs(offsetZ) > 50 and iteration != 3:
            iteration += 1
            self.logger.info(f'Staring iteration {iteration}')
            alignments = []
            stageZ = sem.ReportStageXYZ()[2]
            sem.TiltTo(tilt_to)
            currentAngle = int(sem.ReportTiltAngle())
            sem.Search()
            loop = 0
            while currentAngle > 0:
                loop += 1
                sem.TiltBy(increments)
                currentAngle = int(sem.ReportTiltAngle())
                sem.Search()
                sem.AlignTo('B', 1)
                alignments.append(sem.ReportAlignShift()[5] / math.sin(math.radians(abs(increments) * loop)))

            # self.logger.debug(', '.join(alignments))
            offsetZ = sum(alignments) / (len(alignments) * 1000)
            totalZ = stageZ + offsetZ
            if abs(totalZ) < max_movement:
                self.logger.info(f'Moving by {offsetZ} um')

                sem.MoveStage(0, 0, offsetZ)
                time.sleep(0.2)
            else:
                self.logger.info('Eucentric alignement would send the stage too far, stopping Eucentricity.')
                break
        sem.SetBinning('S', int(binning))
        self.logger.info(f'Eucentric heigh done, setting Search binning back to {binning}.')
    
    def eucentric_height_after_distance(self, tilt_to:int=10, increments:int=-5, max_movement:int=200, distance_threshold:int=400):
        last_eucentric_height_distance = self.state.get_last_eucentric_distance()
        if last_eucentric_height_distance < distance_threshold:
            self.logger.info(f'Last eucentric height distance was {last_eucentric_height_distance} um (Threshold {distance_threshold} um), skipping eucentric height by tilt.')
            return
        self.logger.info(f'Last eucentric height distance was {last_eucentric_height_distance} um (Threshold {distance_threshold} um), running eucentric height by tilt.')
        self.eucentricHeight(tilt_to, increments, max_movement)

    def eucentricity_by_beam_tilt(self, max_movement:int=200, beam_tilt_angle:int=2):
        binning = sem.ReportBinning('V')
        self.logger.info(f'Doing eucentric height by beam tilt, setting View binning to 4.')
        sem.SetBinning('V', 4)
        sem.GoToLowDoseArea('V')

        target_Z = sem.ReportLDDefocusOffset('V')
        sem.SetEucentricFocus(1)
        sem.ChangeFocus(target_Z)
        offsetZ = 51
        iteration = 0
        while abs(offsetZ) > 5 and iteration != 3:
            iteration += 1
            self.logger.info(f'Staring iteration {iteration}')
            alignments = []
            stageZ = sem.ReportStageXYZ()[2]
            sem.SetBeamTilt(-beam_tilt_angle, 0)
            sem.View()
            sem.SetBeamTilt(beam_tilt_angle, 0)
            sem.View()
            sem.AlignTo('B', 1)
            shift = sem.ReportAlignShift()[5]/1000

            # self.logger.debug(', '.join(alignments))
            offsetZ = shift/(beam_tilt_angle*0.002) + target_Z
            self.logger.info(f'Iteration {iteration} offset calculate to {offsetZ}')
            # break
            totalZ = stageZ + offsetZ
            if abs(totalZ) < max_movement:
                self.logger.info(f'Moving by {offsetZ} um')

                sem.MoveStage(0, 0, offsetZ)
                time.sleep(0.2)
            else:
                self.logger.info('Eucentric alignement would send the stage too far, stopping Eucentricity.')
                break  
        sem.SetBinning('V', binning)
        self.logger.info(f'Eucentric heigh done, setting View binning back to {binning}.')      

    def eucentricity(self):
        binning = sem.ReportBinning('V')
        self.logger.info(f'Doing eucentric height, setting View binning to 4.')
        sem.SetBinning('V', 4)
        sem.GoToLowDoseArea('V')
        sem.Eucentricity(1)
        self.logger.info(f'Eucentric heigh done, setting View binning back to {binning}.')
        sem.SetBinning('V', int(binning))

    def setup_serialem(self):
        if sem.ReportIfNavOpen() == 0:
            self.logger.info('Opening SerialEM Navigator since it will be needed.')
            sem.OpenNavigator()
    
    def eucentricity_by_focus(self):
       
        self.logger.info(f'Doing eucentric height by beam tilt, setting View binning to 4.')
        binning = sem.ReportBinning('V')
        sem.SetBinning('V', 4)
        sem.GoToLowDoseArea('V')
        sem.Eucentricity(-1,-1)
        self.logger.info(f'Eucentric heigh done, setting View binning back to {binning}.')
        sem.SetBinning('V', int(binning))
    
    def call(self, script):
        sem.Call(script)

    def call_function(self, function:str, *args):
        str_args = [str(arg) for arg in args]
        sem.CallFunction(f"{function} {' '.join(str_args)}")
    
    def get_image_settings(self, magSet:str='V'):
        return sem.ReportCurrentPixelSize(magSet)
    
    def report_stage(self):
        return sem.ReportStageXYZ()
    
    def set_atlas_optics(self):
        self.logger.info('Setting atlas optics')
        self.logger.debug('Deactivating low dose mode')
        sem.SetLowDoseMode(0)
        self.logger.debug('Setting atlas mag')
        sem.SetMag(self.atlas_settings.mag)
        self.logger.debug('Setting spot size')
        sem.SetSpotSize(self.atlas_settings.spotSize)
        self.logger.debug('Setting C2 percent')
        sem.SetPercentC2(self.atlas_settings.c2)
        self.logger.info('Done setting atlas optics')
    
    def set_atlas_optics_delay(self, delay:int=1):
        self.logger.info(f'Setting atlas optics with a {delay} sec delay between each command.')
        self.logger.debug('Deactivating low dose mode')
        sem.SetLowDoseMode(0)
        time.sleep(delay)
        self.logger.debug('Setting atlas mag')
        sem.SetMag(self.atlas_settings.mag)
        time.sleep(delay)
        self.logger.debug('Setting spot size')
        sem.SetSpotSize(self.atlas_settings.spotSize)
        time.sleep(delay)
        self.logger.debug('Setting C2 percent')
        sem.SetPercentC2(self.atlas_settings.c2)
        time.sleep(delay)
        self.logger.info('Done setting atlas optics')

    def set_atlas_optics_imaging_state(self, state_name:str='Atlas'):
        self.logger.info(f'Setting atlas optics from the {state_name} imaging state')
        sem.GoToImagingState(state_name)
        self.logger.info('Done setting atlas optics')

    
    def reset_stage(self):
        self.logger.info(f'Resetting stage to center.')
        sem.TiltTo(0)
        sem.MoveStageTo(0,0,0)

    def remove_slit(self):
        if not self.detector.energyFilter:
            return
        if sem.ReportEnergyFilter()[2] == 1:
            self.logger.info('Removing slit.')
            sem.SetSlitIn(0)
        
    def atlas(self, size, file=''):
        self.state.current_mag = 'atlas'
        sem.OpenNewMontage(size[0],size[1], file)
        sem.SetMontageParams(1)
        sem.ParamSetToUseForMontage(1)
        self.checkDewars()
        self.checkPump()
        self.logger.info('Starting Atlas acquisition')
        sem.Montage()
        self._add_vectors_to_mdoc(buffer='B')
        sem.CloseFile()
        self.logger.info('Atlas acquisition finished')

    def atlas_in_low_dose_search(self, size, file=''):
        self.state.current_mag = 'atlas'
        sem.GoToLowDoseArea('S')
        sem.SetEucentricFocus()
        sem.ParamSetToUseForMontage(3)
        self.atlas(size, file)
        msg = 'Atlas finished, Restoring Search state.'
        self.logger.info(msg)
        sem.RestoreState()

    def _add_vectors_to_mdoc(self, buffer='A'):
        binning_tile = sem.ImageProperties('A')[2]
        binning = sem.ImageProperties(buffer)[2] / binning_tile
        image_to_stage_matrix = np.array(sem.BufImageToStageMatrix(buffer, 1))
        image_to_stage_matrix /= np.array([binning, binning, binning, binning, 1, 1])
        image_to_stage_matrix = [str(x) for x in image_to_stage_matrix.tolist()]
        stage_to_image_matrix = np.array(sem.StageToBufImageMatrix(buffer, 1))
        stage_to_image_matrix /= np.array([binning, binning, binning, binning, 1, 1])
        stage_to_image_matrix = [str(x) for x in stage_to_image_matrix.tolist()]
        sem.AddToAutodoc('ImageToStageMatrix', ' '.join(image_to_stage_matrix))
        sem.AddToAutodoc('StageToImageMatrix', ' '.join(stage_to_image_matrix))
        sem.WriteAutodoc()

    def save_image(self, file:str):
        # image_to_stage_matrix = sem.BufImageToStageMatrix('A', 1)
        # image_to_stage_matrix = [str(x) for x in image_to_stage_matrix]
        sem.SetFileOptions(0,1,0,1,1,1)
        sem.OpenNewFile(file)
        sem.Save()
        self._add_vectors_to_mdoc()
        # sem.AddToAutodoc('ImageToStageMatrix', ' '.join(image_to_stage_matrix))
        # sem.WriteAutodoc()
        sem.CloseFile()

    def recenter_beam(self, interval_in_minutes:int=5):
        if interval_in_minutes < 0 or self.state.time_since_last_autocenter < interval_in_minutes * 60:
            self.logger.info(f'Time since last autocenter: {self.state.time_since_last_autocenter}. Skipping beam centering')
            return
        self.logger.info('Running beam centering.')
        sem.Trial()
        sem.CenterBeamFromImage()
        sem.Trial()
        self.state.last_autocenter_time = time.time()

    def square(self, file=''):
        self.state.current_mag = 'square'
        sem.SetLowDoseMode(1)
        sem.GoToLowDoseArea('S')
        self.checkDewars()
        self.checkPump()
        sem.Search()
        self.save_image(file)
        self.logger.info('Square acquisition finished')

    def get_mag_area_in_microns(self, magSet='V'):
        area_x_pix, area_y_pix = sem.ReportCameraSetArea(magSet)[:2]
        pixel_size = sem.ReportCurrentPixelSize(magSet)
        area_x_um = area_x_pix * pixel_size / 1000
        area_y_um = area_y_pix * pixel_size / 1000
        return area_x_um, area_y_um

    def medium_mag_montage(self, size, file=''):
        self.state.current_mag = 'medium_mag_montage'
        sem.ParamSetToUseForMontage(2)
        sem.OpenNewMontage(size[0],size[1], file)
        sem.SetMontageParams(2)
        
        self.checkDewars()
        self.checkPump()
        self.logger.info('Starting medium mag montage acquisition')
        sem.Montage()
        self._add_vectors_to_mdoc(buffer='B')
        sem.CloseFile()
        self.logger.info('Medium mag montage acquisition finished')
    
    def buffer_to_numpy(self, buffer:str='A') -> Tuple[np.array, int, int, int, float, float]:
        delay = 1
        sem.Delay(1)
        shape_x, shape_y, binning, exposure, pixel_size, _ = sem.ImageProperties(buffer)
        while True:
            try:
                buffer = sem.bufferImage(buffer)
                break
            except sem.PyBufferImage:
                self.logger.error(f"Error getting the buffer image. Trying again in {delay} seconds.")
                sem.Delay(delay)
                delay +=1
            except sem.SEMerror as e:
                self.logger.error(f"SEM error getting the buffer image. Trying again in {delay} seconds.")
                sem.Delay(delay)
                delay +=1
        self.logger.info(f"Downloaded the buffer image successfully.")
        return np.asarray(buffer), shape_x, shape_y, binning, exposure, pixel_size

    def numpy_to_buffer(self,image,buffer='T'):
        sem.PutImageInBuffer(image, buffer, *image.shape, 'A')
        
    def find_square_center_microns(self):
        sem.Search()
        sem.Delay(0.2, 's')
        square, shape_x, shape_y, _, _, _ = self.buffer_to_numpy()
        _, square_center, _ = find_square(square)
        im_center = (square.shape[1] // 2, square.shape[0] // 2)
        diff = square_center - np.array(im_center)
        self.logger.info(f'Found square center: {square_center}. Image-shifting by {diff} pixels')
        sem.ImageShiftByPixels(int(diff[0]), -int(diff[1]))
        shift = sem.ReportImageShift()[-2:]
        return shift

    def realign_to_square(self):
        self.tiltTo(0)
        init_x, init_y, init_z = sem.ReportStageXYZ()
        while True:
            self.logger.info('Running square realignment')
            sem.Search()
            sem.Delay(0.2, 's')
            square, shape_x, shape_y, _, _, _ = self.buffer_to_numpy()
            _, square_center, _ = find_square(square)
            im_center = (square.shape[1] // 2, square.shape[0] // 2)
            diff = square_center - np.array(im_center)
            self.logger.info(f'Found square center: {square_center}. Image-shifting by {diff} pixels')
            sem.ImageShiftByPixels(int(diff[0]), -int(diff[1]))
            sem.ResetImageShift()
            if max(diff) < max(square.shape) // 4:
                self.logger.info('Done.')
                sem.Search()
                break
            self.logger.info('Iterating.')
        final_x, final_y, final_z = sem.ReportStageXYZ()
        self.state.lastSquareCenteringShiftX = final_x - init_x
        self.state.lastSquareCenteringShiftY = final_y - init_y
        return final_x, final_y, final_z

    def realign_to_square_medium_mag(self, max_image_shift:float=7.0):
        self.tiltTo(0)
        init_x, init_y, init_z = sem.ReportStageXYZ()
        sem.GoToLowDoseArea('V')
        image_shift_steps = [(0,0), 
                             (max_image_shift,0), 
                             (np.cos(0.78)*max_image_shift, np.sin(0.78)*max_image_shift), 
                             (0,max_image_shift),
                             (np.cos(2.26)*max_image_shift, np.sin(2.26)*max_image_shift), 
                             (-max_image_shift,0),
                             (np.cos(3.83)*max_image_shift, np.sin(3.83)*max_image_shift), 
                             (0,-max_image_shift),
                             (np.cos(5.41)*max_image_shift, np.sin(5.41)*max_image_shift),]
        #image shift around to find signal
        self.logger.info(f'Image shifting around to find square in medium mag. Max image shift {max_image_shift} um.')
        self.logger.debug(f'Image shift steps: {image_shift_steps}')
        while True:
            found_square = False
            for shift in image_shift_steps:
                self.logger.info(f'Image shifting to {shift}')
                sem.ImageShiftByMicrons(shift[0], shift[1])
                # sem.ResetImageShift()
                sem.View()
                mean, std, min, max = sem.ReportMeanCounts('A', 2)
                self.logger.debug(f'Mean: {mean}, Std: {std}, Min: {min}, Max: {max}')
                if mean < 20:
                    self.logger.info(f'Image seems to be mostly empty. Trying next image shift.')
                    continue
                self.logger.info(f'Image seems to have signal.')
                found_square = True
                break
            if found_square:
                sem.ResetImageShift()
                break
            self.logger.info('Could not find square in medium mag with the current image shift range. Trying again.')

        while True:
            sem.View()
            self.logger.info('Running square realignment')
            square, shape_x, shape_y, _, _, _ = self.buffer_to_numpy()
            _, square_center, _ = find_square(square)
            im_center = (square.shape[1] // 2, square.shape[0] // 2)
            diff = (square_center - np.array(im_center))*2
            self.logger.info(f'Found square center: {square_center}. Image-shifting by {diff} pixels')
            sem.ImageShiftByPixels(int(diff[0]), -int(diff[1]))
            sem.ResetImageShift()
            shift_lenght_in_pixels = np.linalg.norm(diff)
            max_image_size = np.max(square.shape)
            self.logger.debug(f'Shift length in pixels: {shift_lenght_in_pixels}. Max image size: {max_image_size}, quarter max image size: {max_image_size//4}, {shift_lenght_in_pixels < max_image_size // 4}')
            if shift_lenght_in_pixels < max_image_size // 4:
                self.logger.info('Done.')
                sem.View()
                break
            self.logger.info('Iterating.')
        final_x, final_y, final_z = sem.ReportStageXYZ()
        self.state.lastSquareCenteringShiftX = final_x - init_x
        self.state.lastSquareCenteringShiftY = final_y - init_y
        return final_x, final_y, final_z
            

    def align_to_hole_ref(self):
        sem.View()
        self.logger.debug(f'Aligning to hole reference. Cropping view image to {self.hole_crop_size}x{self.hole_crop_size}')
        sem.CropCenterToSize('A', self.hole_crop_size, self.hole_crop_size)
        sem.Delay(0.5)
        sem.AlignTo('T')
        return sem.ReportAlignShift()
    
    def align_to_coord(self, coord):
        sem.ImageShiftByPixels(coord[0], coord[1])
        sem.ResetImageShift()
        return sem.ReportStageXYZ()
    
    def setFocusPosition(self, distance, angle):
        sem.SetAxisPosition('F', distance, angle)
        self.focus_position_set = True

    def moveStage(self,stage_x,stage_y,stage_z=None):
        sem.SetImageShift(0, 0)
        
        args = [stage_x, stage_y]
        if stage_z is not None:
            args.append(stage_z)
        self.logger.info(f'Moving stage to {args}.')
        sem.MoveStageTo(*args)
        self.state.setStage(*args)
    
    def get_conversion_matrix(self, magIndex=0):
        return sem.CameraToSpecimenMatrix(magIndex)

    def load_hole_ref(self):
        sem.ReadOtherFile(0, 'T', 'reference/holeref.mrc')
        shape_x, _, _, _, _, _ = sem.ImageProperties('T')
        self.hole_crop_size = int(shape_x)
        self.has_hole_ref = True

    def acquire_medium_mag(self):
        self.state.current_mag = 'hole'
        sem.GoToLowDoseArea('V')
        time.sleep(1)
        self.checkDewars()
        self.checkPump()
        sem.View()

    def tiltTo(self,tiltAngle):
        if self.state.tiltAngle == tiltAngle:
            return
        sem.TiltTo(tiltAngle)
        self.state.tiltAngle = tiltAngle

    def medium_mag_hole(self, file=''):
        sem.AllowFileOverwrite(1)
        self.acquire_medium_mag()
        self.save_image(file)

    def save_eucentric_focus(self):
        if self.state.eucentricDefocus is None:
            sem.SetEucentricFocus()
            self.state.eucentricDefocus = sem.ReportDefocus()

    def roll_defocus(self, def1, def2, step):
        sem.GoToLowDoseArea('Record')
        self.save_eucentric_focus()
        self._rollDefocus(def1, def2, step)
        sem.SetTargetDefocus(self.state.defocusTarget)

    def autofocus_by_z(self) -> bool:
        sem.SetDefocus(self.state.eucentricDefocus)
        defocus = 99999
        iteration = 0
        total_movement = 0
        while True:
            iteration += 1
            self.logger.info(f'Starting iteration {iteration}.')
            sem.AutoFocus(-1)
            defocus, error_code = sem.ReportAutoFocus()
            movement = (defocus - self.state.defocusTarget)*-1
            if error_code != 0:
                self.logger.info('Autofocus seems to have failed')
                return False
            if abs(defocus-self.state.defocusTarget) < 0.5:
                sem.ChangeFocus(movement)
                break
            self.logger.info(f'Defocus measured at {defocus:.2f} um, moving stage by {movement:.2f}')
            sem.MoveStage(0,0, movement)
            total_movement += movement
        self.logger.info(f'Autofocus by Z finished after {iteration} iterations and a total movement of {total_movement:.2f}')
        return True

    def autofocus(self, def1, def2, step):
        sem.AutoFocus()
        defocus, error_code = sem.ReportAutoFocus()
        self.state.add_to_last_five_defocus(defocus)
        if error_code in [1,2,3,-1]:
            self.logger.error(f'Autofocus failed with error code {error_code}.')
            
        self.state.currentDefocus = sem.ReportDefocus()
        self.state.set_last_autofocus_position()

    def wait_drift(self, drifTarget):
        if drifTarget > 0:
            sem.DriftWaitTask(drifTarget, 'A', 300, 10, -1, 'F', 1)

    def connect(self):
        logger.info(
            f"""
            Initiating connection to SerialEM at: {self.microscope.ip}:{self.microscope.port}
            If no more messages show up after this one and the External Control notification 
            is not showing up on the SerialEM interface, there is a problem.
            The best way to solve it is generally by closing and restarting SerialEM.
            """
        )
        sem.ConnectToSEM(self.microscope.port, self.microscope.ip)
        sem.SetDirectory(self.microscope.directory)
        sem.ClearPersistentVars()
        sem.AllowFileOverwrite(1)

    def setup(self, saveframes:bool, frames_dir:str='', framesName=None):
        if saveframes:
            self.logger.info('Saving frames enabled')
            sem.SetDoseFracParams('R', 1, 1, 0)
            self.logger.info(f'SerialEM will be saving frames to {frames_dir}')
            sem.SetFolderForFrames(frames_dir)
            if framesName is not None:
                sem.SetFrameBaseName(0, 1, 0, framesName)
        else:
            self.logger.info('Saving frames disabled')
            # sem.SetDoseFracParams('R', 1, 0, 0)

        sem.KeepCameraSetChanges('R')
        sem.SetLowDoseMode(1)
        sem.SetBufferImageTimeout(5)

    def refineZLP(self, zerolossDelay:float):
        if not self.detector.energyFilter:
            return
        if zerolossDelay < 0:
            self.logger.info('Refine ZLP disabled')
            return
        if self.state.last_refine_zlp_success:
            zerolossDelay = 0
        success = sem.RefineZLP(zerolossDelay * 60, 0, 0, 1)
        self.state.last_refine_zlp_success = True if success == 0 else False
        if self.state.last_refine_zlp_success:
            self.logger.info('Refine ZLP successful')
            return
        self.logger.info('Refine ZLP failed. Will try again after the next area')
            
    
    def collectHardwareDark(self, harwareDarkDelay:int):
        if harwareDarkDelay > 0:
            sem.UpdateHWDarkRef(harwareDarkDelay)

    def disconnect(self):
        
        self.logger.info("Closing Valves and disconnecting from SerialEM")
        if self.close_valves_on_disconnect:
            try:
                sem.SetColumnOrGunValve(0)
            except:
                logger.warning("Could not close the column valves, still disconnecting from SerialEM")
        sem.Exit(1)

    def load_grid(self, position):
        if self.microscope.loaderSize > 1:
            slot_status = sem.ReportSlotStatus(position)

            #This was added to support the new 4.1 2023-02-27 version 
            # that reports the name of the grid along with the position
            if isinstance(slot_status,tuple):
                slot_status = slot_status[0]
            
            if slot_status == -1:
                raise ValueError(f'SerialEM return an error when reading slot {position} of the autoloader.')
            if slot_status == 1:
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
                slot_status = slot_status[0]
            if  slot_status != 0:
                raise CartridgeLoadingError('Cartridge did not load properly. Stopping')
        # sem.SetColumnOrGunValve(1)

    def open_valves(self):
        sem.Delay(2)
        sem.SetColumnOrGunValve(1)

    def unload_grid(self):
        self.logger.info(f'Unloading finished grid.')
        return sem.UnloadCartridge()

    def zero_image_shift(self):
        return sem.SetImageShift(0,0)

    def reset_image_shift(self):
        return sem.ResetImageShift()
    
    def reset_image_shift_values(self):
        self.state.reset_image_shift_values()


    def save_AFIS_image_shift(self, afis:bool=False):
        sem.GoToLowDoseArea('Record')
        self.state.preAFISimageShiftX, self.state.preAFISimageShiftY = sem.ReportImageShift()[:2]
        if afis:
            sem.SaveBeamTilt()
    
    def reset_AFIS_image_shift(self, afis:bool=False):
        sem.SetImageShift(self.state.preAFISimageShiftX, self.state.preAFISimageShiftY, 1, int(afis))
        if afis:
            sem.RestoreBeamTilt()

    def image_shift_by_microns(self,isX,isY,tiltAngle, afis:bool=False, goToRecord=True, delay_multiplier=1, additional_delay=0):
        self.logger.debug(f'Image shift by microns: {isX}, {isY}, {tiltAngle}, {afis}, {goToRecord}, {delay_multiplier}, {additional_delay}')
        if goToRecord:
            sem.GoToLowDoseArea('Record')
        sem.ImageShiftByMicrons(isX - self.state.imageShiftX, isY - self.state.imageShiftY, delay_multiplier, int(afis))
        if goToRecord:
            self.state.imageShiftX = isX
            self.state.imageShiftY = isY
        if additional_delay > 0:
            time.sleep(additional_delay)

    def set_focus_for_bis_tilt(self,isY,tiltAngle):
        if tiltAngle == 0:
            return
        sem.SetDefocus(self.state.currentDefocus - isY * math.sin(math.radians(tiltAngle)))     

    def highmag(self, file='', frames=True, earlyReturn=False):

        if not earlyReturn:
            sem.EarlyReturnNextShot(0)

        sem.Record()
        if earlyReturn:
            sem.OpenNewFile(file)
            sem.Save()
            sem.CloseFile()

        if frames:
            frames = sem.ReportLastFrameFile()
            if isinstance(frames, tuple):  
                # Workaround since the output of the ReportFrame 
                # command changed in 4.0, need to test ans simplify
                frames = frames[0]
            self.logger.debug(f"Frames: {frames},")
            return frames.split('\\')[-1]
        
    def get_property(self, property_name:str):
        return sem.ReportProperty(property_name)
    

    def report_aperture_size(self, aperture:int):
        aperture_size = self.state.get_aperture_state(aperture)
        if not aperture_size is None:
            return aperture_size
        aperture_size = int(sem.ReportApertureSize(aperture))
        self.state.set_aperature_state(aperture, aperture_size)
        return aperture_size
           
    def remove_aperture(self,aperture:int, wait:int=10):
        inital_aperture_size = self.report_aperture_size(aperture)
        if inital_aperture_size == 0:
            self.logger.info( f'Aperture {aperture} already out.')
            return
        self.logger.info( f'Removing aperture {aperture} and waiting {wait}s.')
        sem.RemoveAperture(aperture)
        self.state.set_aperature_state(aperture, 0)
        time.sleep(wait)
        
    def insert_aperture(self, aperture:int, aperture_size:int, wait:int=10):
        if self.report_aperture_size(aperture) == aperture_size:
            self.logger.info( f'Aperture {aperture} already at {aperture_size}.')
            return
        self.logger.info( f'Inserting/Changing aperture {aperture} to {aperture_size} and waiting {wait}s.')
        sem.SetApertureSize(aperture, aperture_size)
        time.sleep(wait)
        self.state.set_aperature_state(aperture, aperture_size)

    def set_apertures_for_highmag(self, highmag_aperture_size:int, objective_aperture_size:int):
        if not self.microscope.apertureControl:
            return
        self.insert_aperture(self.apertures.OBJECTIVE, objective_aperture_size)
        self.insert_aperture(self.apertures.CONDENSER, highmag_aperture_size)

    def set_apertures_for_lowmag(self):
        if not self.microscope.apertureControl:
            return
        self.remove_aperture(self.apertures.OBJECTIVE)
        if self.atlas_settings.atlas_c2_aperture == 0:
            self.remove_aperture(self.apertures.CONDENSER)
            return
        self.insert_aperture(self.apertures.CONDENSER, self.atlas_settings.atlas_c2_aperture)

    def autofocus_after_distance(self, def1, def2, step, distance):
        last_autofocus_distance = self.state.get_last_autofocus_distance()
        if last_autofocus_distance > distance:
            self.logger.info(f'Last autofocus distance was {last_autofocus_distance} um (Threshold {distance} um), running autofocus')
            return self.autofocus(def1, def2, step)
        self.logger.debug(f'Last autofocus distance was {last_autofocus_distance} um (Threshold {distance} um), skipping autofocus.')
        defocus_target = self.state.defocusTarget
        current_defocus = self.state.currentDefocus
        new_defocus_target = self._rollDefocus(def1, def2, step)
        defocus_change = new_defocus_target - defocus_target
        self.logger.debug(f'Last defocus target: {defocus_target}. New defocus target: {defocus_target}. Change: {defocus_change}')
        sem.SetTargetDefocus(new_defocus_target)
        self.state.currentDefocus += defocus_change
        self.logger.debug(f'Current defocus: {current_defocus}. New current defocus: {self.state.currentDefocus}')
        if defocus_change != 0:
            sem.ChangeFocus(defocus_change)
            return
        
    def set_highmag_counting_mode(self):
        if self.detector.detectorModel in ['K2','Ceta']:
            return
        sem.SetK2ReadMode('R', 1)
        sem.SetK2ReadMode('P', 1)
        sem.SetK2ReadMode('F', 1)

    def check_medium_mag_size(self, hole_pitch_um:float=2.5):
        x_size, y_size = sem.ReportCameraSetArea('V')[:2]
        pixel_size = sem.ReportCurrentPixelSize('V')
        x_size_um = x_size * pixel_size / 1000
        y_size_um = y_size * pixel_size / 1000
        return x_size_um, y_size_um
    
    def set_medium_mag_size_mini_montage(self, hole_pitch_um:float=2.5):
        x_size_um, y_size_um = self.check_medium_mag_size(hole_pitch_um)
        min_size_um = min(x_size_um, y_size_um)
        if min_size_um > hole_pitch_um * 3:
            self.logger.warning(f'Medium mag image size is {x_size_um:.2f} x {y_size_um:.2f} um, which may be too large for reliable for geometry calculation.')
        num_tiles_x = math.ceil(x_size_um / 7)
        num_tiles_y = math.ceil(y_size_um / 7)
        self.logger.info(f'Medium mag image size is {x_size_um:.2f} x {y_size_um:.2f} um. This corresponds to {num_tiles_x} x {num_tiles_y} tiles of 7 um for hole detection.')



