from typing import Dict
from random import random
import os
import numpy as np
import logging
from Smartscope.core.interfaces.microscope_interface import MicroscopeInterface
from Smartscope.core.grid.diagnostics import save_reregistration_diagnostics


logger = logging.getLogger(__name__)

def setAtlasOptics(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Set the microscope mag, spot size and C2 current for the atlas based on the chosen detector."""
    scope.set_apertures_for_lowmag()
    scope.set_atlas_optics()

def setAtlasOpticsDelay(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Same as setAtlasOptics with delays between each commands."""
    delay=content.get('delay',1)
    scope.set_apertures_for_lowmag()
    scope.set_atlas_optics_delay(delay=delay)

def setAtlasOpticsImagingState(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Sets the atlas optics from an Imaging State named "Atlas"."""
    scope.set_apertures_for_lowmag()
    scope.set_atlas_optics_imaging_state(state_name='Atlas')

def resetStage(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Resets the stage to the center of the image."""
    scope.reset_stage()

def removeSlit(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Removes the slit from the beam path."""
    scope.remove_slit()

def call(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) -> None:
    """Calls any script that is saved in the SerialEM scripts."""
    script = content.get('script', None)
    assert script is not None, 'No script was specified'
    scope.call(script=script)
    return instance

def callFunction(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) -> None:
    """Calls any function that is saved in the SerialEM scripts."""
    function = content.get('function', None)
    assert function is not None, 'No function was specified'
    scope.call_function(function=function, *args)
    return instance

def atlas(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Collects and atlas of X by Y tiles from the collection parameters using the Montage command"""
    scope.atlas(size=[params.atlas_x,params.atlas_y],file=instance.raw)

def atlasInLowDoseSearch(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    scope.atlas_in_low_dose_search(size=[params.atlas_x,params.atlas_y],file=instance.raw)

def realignToSquare(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Realigns to the square using the Search magnification. 
    Mainly useful when the alignement between the Atlas and the Square is off.
    """
    # from Smartscope.core.db_manipulations import set_or_update_refined_finder
    stageX, stageY, stageZ = scope.realign_to_square()
    # set_or_update_refined_finder(instance.square_id, stageX, stageY, stageZ)
    scope.moveStage(stageX,stageY,stageZ)   

def square(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Acquires and save the square image using the Search preset."""
    scope.square(file=instance.raw)

def squareInMediumMag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Acquires and save the square image using the View preset."""
    if params.square_x > 1 or params.square_y > 1:
        n_tiles_x = params.square_x
        n_tiles_y = params.square_y
    else:
        size_x, size_y = scope.get_mag_area_in_microns(magSet='V')
        area = instance.selectors.filter(method_name='Size selector').first().value
        total_area_size = np.sqrt(area) * 1.3
        logger.debug(f'Medium mag size in A: {size_x} x {size_y}, total area size: {total_area_size}')
        n_tiles_x = int(np.ceil(total_area_size / size_x))
        n_tiles_y = int(np.ceil(total_area_size / size_y))
    scope.medium_mag_montage(size=[n_tiles_x, n_tiles_y], file=instance.raw)

def moveStage(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Moves the stage to the instance position"""
    finder = instance.finders.order_by('-created_at').first()
    stage_x, stage_y, stage_z = finder.stage_x, finder.stage_y, finder.stage_z
    scope.moveStage(stage_x,stage_y,stage_z=stage_z)

def moveStageWithAtlasToSearchOffset(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs)  -> None:
    """Moves the stage to the instance position with an offset"""
    offset_x = scope.atlas_settings.atlas_to_search_offset_x + scope.state.lastSquareCenteringShiftX
    offset_y = scope.atlas_settings.atlas_to_search_offset_y + scope.state.lastSquareCenteringShiftY
    finder = instance.finders.order_by('-created_at').first()
    stage_args = [finder.stage_x + offset_x, finder.stage_y + offset_y]
    if instance.prefix.lower() != 'square':
        stage_args.append(finder.stage_z)
    scope.moveStage(*stage_args)

def autoFocus(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Acquires the focus drift image using the Search preset."""
    scope.autofocus(
        params.target_defocus_min,
        params.target_defocus_max,
        params.step_defocus,
    )

def waitDrift(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Waits for the drift to settle."""
    scope.wait_drift(params.drift_crit)

def eucentricSearch(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Calculates eucentricity using the Search preset. 
    
    This is faster than using the built-in serialEM Eucentricity by not having to switch the optics back and forth between View and Search. Will speed up screening.
    
    However, this is less precise than Eucentricty and should be avoided when using Falcon detectors or when setting up for data collection.
    """
    if scope.microscope.narrowGapPolepiece:
        logger.info('Narrow gap polepiece detected, using eucentricity by focus instead of stage tilt.')
        scope.eucentricity_by_focus()
    scope.eucentricHeight()

def eucentricMediumMag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Calculates eucentricity using the View preset. Equivalent to Eucentric Rough."""
    if scope.microscope.narrowGapPolepiece:
        logger.info('Narrow gap polepiece detected, using eucentricity by focus instead of stage tilt.')
        scope.eucentricity_by_focus()
    scope.eucentricity()
    instance.eucentricity_refined = True
    instance.save()

def eucentricByBeamTilt(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Calculates eucentricity using the View preset using beam tilt instead of stage tilt. Equivalent to Eucentric Rough."""
    scope.eucentricity_by_focus()

def mediumMagHole(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Acquires the hole at the View preset."""
    scope.medium_mag_hole(file=instance.raw)

def tiltToAngle(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    scope.tiltTo(params.tilt_angle)

def alignToHoleRef(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Aligns the medium mag to the template hole image stored in buffer T. Either load an image manually or use the loadHoleRef command prior to this one."""
    max_iterations = content.get('max_iterations', 3)
    iteration = 0
    while iteration < max_iterations:
        iteration +=1
        if iteration > 1:
            scope.image_shift_by_microns(0.2,0, tiltAngle=params.tilt_angle, goToRecord=False)
        shift = scope.align_to_hole_ref()
        if np.sqrt(np.sum(np.array(shift[-2:])**2)) < 500:
            return
        scope.reset_image_shift()
    logger.warning(f'It seems like the hole realignment did not converge after {max_iterations} iterations.')

def zeroImageShift(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    scope.zero_image_shift()
    scope.reset_image_shift_values()

def setAFISimageShift(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    scope.save_AFIS_image_shift(afis=params.afis)

def loadHoleRef(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Loads the references/holeref.mrc image into buffer T to be used as hole template for the alignToHoleRef command."""
    if scope.has_hole_ref:
        return
    scope.load_hole_ref()

def setHighMagOptics(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Sets the high mag optics."""
    if content.get('set_apertures', True):
        scope.set_apertures_for_high_mag(condenser_aperture_size=params.highmag_aperture_size, objective_aperture_size=params.objective_aperture_size)
    scope.set_high_mag_optics()

def setMediumMagOptics(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Sets the medium mag optics."""
    scope.set_apertures_for_medium_mag(condenser_aperture_size=params.highmag_aperture_size, objective_aperture_size=params.objective_aperture_size)
    scope.set_medium_mag_optics()

def setSquareMagOptics(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Sets the square mag optics."""
    scope.set_apertures_for_square_mag()
    scope.set_square_mag_optics()

def highMag(scope:MicroscopeInterface, params,instance, content:Dict, *args, **kwargs) :
    """Acquires the highmag image. 
    
    Will set image shift and the specificed offset from the collection parameters.
    
    Also automatically corrects defocus and image-shift based on the tilt angle.
    """
    delay_multiplier = content.get('delay_multiplier', 1)
    additional_delay = content.get('additional_delay', 0)

    finder = instance.finders.first()
    stage_x, stage_y, _ = scope.report_stage()
    grid = instance.grid_id
    grid_type = grid.holeType
    grid_mesh = grid.meshMaterial
    offset = 0
    if params.offset_targeting and not params.multishot_per_hole and (grid.collection_mode == 'screening' or params.offset_distance != -1) and grid_type.hole_size is not None:
        offset = add_IS_offset(grid_type.hole_size, grid_mesh.name, offset_in_um=params.offset_distance)
    isX, isY = stage_x - finder.stage_x + offset, (stage_y - finder.stage_y) #* cos(radians(params.tilt_angle))
    logger.debug(f'The tilt angle is {params.tilt_angle}, Y axis image-shift corrected from {stage_y - finder.stage_y:.2f} to {isY:.2f}')
    scope.image_shift_by_microns(isX,isY,params.tilt_angle, afis=params.afis, delay_multiplier=delay_multiplier, additional_delay=additional_delay)
    # logger.debug(f'Image shift is {isX},{isY}.')
    scope.set_focus_for_bis_tilt(isY,tiltAngle=params.tilt_angle)
    frames = scope.highmag(file=instance.raw, 
                           frames=params.save_frames, 
                           earlyReturn=any([params.force_process_from_average, params.save_frames is False, 'Falcon' in grid.session_id.detector_id.detector_model]))
    instance.is_x=isX
    instance.is_y=isY
    instance.offset=offset
    instance.frames=frames
    return instance

def add_IS_offset(
        hole_size_in_um: float,
        mesh_type: str,
        offset_in_um: float = -1
    ) -> float:
    if offset_in_um != -1:
        return offset_in_um
    hole_radius = hole_size_in_um / 2
    max_offset_factor = 0.5
    if mesh_type == 'Carbon':
        max_offset_factor = 0.8
    offset_in_um = round(random() * hole_radius * max_offset_factor, 1)
    logger.info(f'Adding a {offset_in_um} \u03BCm offset ' + 
        'to sample ice gradient along the hole.')
    return offset_in_um


def setFocusPosition(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Caculates the rotation and shift of the focus position

    Will calculates the rotation from the identified holes.
    The distance is calculared from the input grid type.
    """
    from Smartscope.core.mesh_rotation import get_mesh_rotation
    if scope.focus_position_set:
        logger.info(f'Focus position was already set')
        return
    pitch = instance.grid_id.holeType.pitch
    if params.tilt_angle == 0:
        try:
            distance = np.round(np.sqrt(pitch**2*2)/2,2)
            angle = get_mesh_rotation(instance.grid_id) -45
            logger.info(f'Setting focus position at {distance} um offset and {angle} degrees rotation')
            scope.setFocusPosition(distance, angle)
            return
        except Exception as err:
            logger.exception(err)
            logger.info('Could not set focus position at the moment since no holes were withing the specified distance.')
    distance = pitch/2
    angle = 0
    logger.info(f'Setting focus at {distance} um offset and {angle} degrees rotation')
    scope.setFocusPosition(distance, angle)

def autoFocusAfterDistance(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Acquires the focus only after a specific distance in microns was traveled. Default: 5 um"""
    logger.debug(f'Running autofocus after distance with params {params} and content {content}')
    distance = content.get('distance', 5)
    scope.autofocus_after_distance(
        params.target_defocus_min,
        params.target_defocus_max,
        params.step_defocus,
        distance
        )

def set_apertures_for_highmag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Sets the apertures for the highmag image."""
    scope.set_apertures_for_high_mag(
        condenser_aperture_size=params.condenser_aperture_size,
        objective_aperture_size=params.objective_aperture_size
    )

def set_apertures_for_lowmag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    scope.set_apertures_for_lowmag()

def createHoleRef(scope,params,instance, content:Dict, *args, **kwargs):
    from Smartscope.core.grid.finders import create_hole_ref_from_image
    if scope.has_hole_ref:
        return
    scope.acquire_medium_mag()
    image, _, _, _, _, pixel_size = scope.buffer_to_numpy()
    average = create_hole_ref_from_image(image, pixel_size, instance.grid_id.holeType.hole_size)
    scope.numpy_to_buffer(average)
    scope.hole_crop_size = average.shape[0]
    scope.has_hole_ref = True

def alignToHoleNoTemplate(scope,params,instance, content:Dict, *args, **kwargs):
    """
    Aligns the hole using MM-finderinstead of a hole reference image. Slower but very precise
    """

    from Smartscope.lib.image.base_image import BaseImage
    from Smartscope.core.grid.finders import find_targets
    from Smartscope.core.db_manipulations import set_or_update_refined_finder
    iteration = 0
    while iteration < 2:
        scope.acquire_medium_mag()
        pixel_size = scope.get_image_settings()
        image, _, _, _, _, pixel_size = scope.buffer_to_numpy()
        print(f'Pixel size is {pixel_size:.3f}')
        montage = BaseImage('recentering')
        montage.image = image
        targets = find_targets(montage, ['Medium Mag AI hole finder'], convert_to_stage=False)[0]

        coords_from_center = np.array([[target.x,target.y] for target in targets]) - np.array([montage.shape_x,montage.shape_y])//2
        dist_to_center = np.sqrt(np.sum(np.power(coords_from_center,2),axis=1))
        closest_index = np.argmin(dist_to_center)
        print(f'Distance to center is {dist_to_center[closest_index] * pixel_size:.3f} nm')
        if dist_to_center[closest_index] * pixel_size < 500: # 500 nm
            print(f'Hole is within the 500 nm threshold, no need to recenter')
            set_or_update_refined_finder(instance.pk,*scope.report_stage())
            break
        iteration += 1
        print(f'Aligning to hole and retrying.')
        scope.align_to_coord(coords_from_center[closest_index])

def findHoleGeometry(scope,params,instance, content:Dict, *args, **kwargs):
    from Smartscope.core.grid.finders import find_targets
    from Smartscope.core.grid.run_io import get_file_and_process
    from Smartscope.lib.mesh_operations import get_mesh_rotation_spacing
    from Smartscope.lib.Datatypes.grid_geometry import GridGeometry, GridGeometryLevel

    grid = instance.grid_id
    os.chdir(grid.directory)
    pitch = grid.holeType.pitch
    num_tiles_x, num_tiles_y = scope.set_medium_mag_size_mini_montage(hole_pitch_um=pitch)
    im_file = 'raw/medium_mag_geometry.mrc'
    if max(num_tiles_x, num_tiles_y) == 1:
        scope.acquire_medium_mag(file=im_file)
    else:
        scope.medium_mag_montage((num_tiles_x, num_tiles_y), file=im_file)

    microscope_id = grid.session_id.microscope_id
    montage = get_file_and_process(
        raw=os.path.join(microscope_id.scope_path, im_file),
        name='medium_mag_geometry',
        force_reprocess=True
    )

    targets = find_targets(montage, ['Medium Mag AI hole finder'])[0]
    stage_coords = np.array([t.stage_coords for t in targets])
    rotation, spacing = get_mesh_rotation_spacing(stage_coords, pitch)
    logger.info(f'Found hole geometry at medium mag: spacing={spacing:.3f} um, rotation={rotation:.2f} deg')

    geometry = GridGeometry.load(directory=grid.directory)
    geometry.set_geometry(level=GridGeometryLevel.MEDMAG, spacing=spacing, rotation=rotation)
    geometry.save(directory=grid.directory)

def refineOpticsForHighMag(scope,params,instance, content:Dict, *args, **kwargs):
    if scope.state.current_mag in ['atlas','square']:
        scope.recenter_beam(interval_in_minutes=0)
        if params.zeroloss_delay != -1:
            scope.refineZLP(zerolossDelay=0)

def callOnModeChange(scope,params,instance, content:Dict, *args, **kwargs):
    if scope.state.current_mag in ['atlas','square']:
        call(scope,params,instance,content,*args, **kwargs)

def rollDefocus(scope,params,instance, content:Dict, *args, **kwargs):
    scope.roll_defocus(
        params.target_defocus_min,
        params.target_defocus_max,
        params.step_defocus,
    )

def autofocusByZ(scope,params,instance, content:Dict, *args, **kwargs):
    scope.autofocus_by_z()

def loadGrid(scope,params,instance, content:Dict, *args, **kwargs):
    scope.load_grid(instance.position)

def unloadGrid(scope,params,instance, content:Dict, *args, **kwargs):
    scope.unload_grid()

def setHighmagCountingMode(scope,params,instance, content:Dict, *args, **kwargs):
    scope.set_highmag_counting_mode()

def resetAFISimageShift(scope,params,instance, content:Dict, *args, **kwargs):
    scope.reset_AFIS_image_shift(afis=params.afis)

def refineZLP(scope,params,instance, content:Dict, *args, **kwargs):
    scope.refineZLP(params.zeroloss_delay)

def collectHardwareDark(scope,params,instance, content:Dict, *args, **kwargs):
    scope.collectHardwareDark(params.hardwaredark_delay)

def flashColdFEG(scope,params,instance, content:Dict, *args, **kwargs):
    scope.flash_cold_FEG(params.coldfegflash_delay)

def recenterBeam(scope,params,instance, content:Dict, *args, **kwargs):
    scope.recenter_beam(params.beam_centering_delay)

def setupFrames(scope,params,instance, content:Dict, *args, **kwargs):
    from .frames import get_serialem_frames_dir, get_smartscope_frames_dir
    session = instance.session_id
    if params.save_frames:
        frames_dir = get_smartscope_frames_dir(instance)
        logger.debug(f'Saving the frames in {frames_dir}')
        frames_dir.mkdir(parents=True, exist_ok=True)
    scope.setup(params.save_frames,frames_dir=get_serialem_frames_dir(instance),framesName=f'{session.date}_{instance.name}')


def setupApertures(scope,params,instance, content:Dict, *args, **kwargs):
    scope.setup_apertures()

def resetState(scope,params,instance, content:Dict, *args, **kwargs):
    scope.reset_state()

def reregisterMediumMag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    from Smartscope.core.grid.run_io import get_file_and_process
    from Smartscope.lib.Finders.basic_finders import find_square
    from Smartscope.lib.image.target import Target

    microscope_id = instance.grid_id.session_id.microscope_id
    finder = instance.finders.first()

    moveStage(scope,params,instance, content, *args, **kwargs)
    squareInMediumMag(scope,params,instance, content, *args, **kwargs)
    montage = get_file_and_process(
            raw=square.raw,
            name=square.name,
            target_directory=instance.name,
            directory=microscope_id.scope_path
        )
    _, square_center, _ = find_square(montage.image)
    t = Target(square_center,from_center=True)
    t.convert_image_coords_to_stage(montage)
    new_stage_x = t.stage_x
    new_stage_y = t.stage_y
    return(new_stage_x, new_stage_y)

def register_medium_to_square(square, medium_montage, expected_px, old_stage, content:Dict=None,
                              diagnostics_dir=None, name:str=None, square_montage=None,
                              return_result:bool=False):
    """[v1] Locates a medium mag image (or mini-montage) in the original square image by matching
    YOLO junk/contaminant detections on both images (reregister_yolo.register).
    ``expected_px`` is the full resolution square pixel where the medium image center was
    targeted in the pre-reload frame, and ``old_stage`` the stage position it was acquired at.

    Returns (old_equiv, new): ``new`` is ``old_stage`` and ``old_equiv`` is the pre-reload stage
    position of what was actually imaged. None if the registration was unreliable.
    With return_result, returns (pair_or_None, result) where result also holds ``shift_px``
    (found - expected, full resolution square pixels) and ``accepted``.
    """
    from Smartscope.lib.image.montage import Montage
    from Smartscope.lib.image.target import Target
    from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast, auto_contrast_sigma, to_8bits
    from Smartscope.tasks.base_tasks import send_find_junk
    from Smartscope.core.reregistration.reregister_yolo import register

    content = content or {}
    name = name or medium_montage.name
    final_height = content.get('final_height', 1024)
    junk_kwargs = dict(
        imgsz=content.get('imgsz', final_height),
        conf_thres=content.get('conf_thres', 0.25),
        iou_thres=content.get('iou_thres', 0.45),
    )
    expected_px = np.asarray(expected_px, dtype=float)
    old_stage = np.asarray(old_stage[:2], dtype=float)

    if square_montage is None:
        square_montage = Montage(square.name, working_dir=square.working_dir)
        square_montage.load_or_process()

    scale_hole = final_height / medium_montage.image.shape[0]
    scale_square = final_height / square_montage.image.shape[0]
    normalizations = {'auto_contrast': auto_contrast, 'auto_contrast_sigma': auto_contrast_sigma, 'none': to_8bits}
    hole_img = convert_to_png(medium_montage.image, height=final_height,
                              normalization=normalizations[content.get('hole_normalization', 'auto_contrast_sigma')])
    square_img = convert_to_png(square_montage.image, height=final_height,
                                normalization=normalizations[content.get('square_normalization', 'auto_contrast')])

    meta = {
        'hole': {
            'pixel_size': medium_montage.pixel_size / scale_hole,
            'rotation_angle': medium_montage.rotation_angle,
        },
        'square': {
            'pixel_size': square_montage.pixel_size / scale_square,
            'rotation_angle': square_montage.rotation_angle,
        },
        'hole_coords_on_square': {'x': expected_px[0] * scale_square, 'y': expected_px[1] * scale_square},
    }
    logger.debug(f'Re-registration metadata for {name}: {meta}')

    det_hole = send_find_junk(
        hole_img, weights=content.get('weights_hole', 'junk_detection/junk_medium_mag.pt'),
        classes=content.get('classes_hole', None),
        **{**junk_kwargs, 'conf_thres': content.get('conf_thres_hole', junk_kwargs['conf_thres'])})
    det_square = send_find_junk(
        square_img, weights=content.get('weights_square', 'junk_detection/junk_square_norm.pt'),
        classes=content.get('classes_square', None),
        **{**junk_kwargs, 'conf_thres': content.get('conf_thres_square', junk_kwargs['conf_thres'])})

    hole_h, hole_w = hole_img.shape[:2]
    medium_center = getattr(medium_montage, 'center_px', None)
    if medium_center is None:
        medium_center = medium_montage.center
    hole_center = np.asarray(medium_center, dtype=float) * scale_hole
    result = register(
        hole_img_path=None,
        hole_shape=(hole_h, hole_w),
        meta=meta,
        hole_coords=np.array([hole_center], dtype=float),
        detections_hole=det_hole,
        detections_square=det_square,
        match_dist_px=content.get('match_dist_px', 15.0),
        ransac_thresh=content.get('ransac_thresh', 3.0),
        min_inliers=content.get('min_inliers', 3),
        verbose=False,
    )
    q = result['hole_coords_sq'][0] / scale_square
    result['shift_px'] = q - expected_px
    result['accepted'] = result['quality'] == 'good'
    logger.info(
        f'YOLO re-registration {name} on {square}: quality={result["quality"]}, transform={result["transform_used"]}, '
        f'det={result["n_detections_h"]}/{result["n_detections_sq"]}, '
        f'matches={result["n_matches"]}, inliers={result["n_inliers"]}, shift={np.round(result["shift_px"], 1)} px'
    )

    if diagnostics_dir is not None:
        save_reregistration_diagnostics(diagnostics_dir, name, hole_img, square_img, result,
                                        np.array([hole_center]), det_hole, det_square)

    if not result['accepted']:
        logger.warning(f'YOLO re-registration of {name} unreliable ({result["quality"]}), discarding.')
        return (None, result) if return_result else None

    t_new = Target(q, from_center=True)
    t_new.convert_image_coords_to_stage(square_montage)
    t_exp = Target(expected_px, from_center=True)
    t_exp.convert_image_coords_to_stage(square_montage)
    delta = t_new.stage_coords - t_exp.stage_coords
    old_equiv = old_stage + delta
    logger.info(f'Re-registration pair for {name}: old={np.round(old_equiv, 3)}, new={np.round(old_stage, 3)} '
                f'(stage delta {np.round(delta, 3)} um)')
    if return_result:
        return (old_equiv, old_stage), result
    return old_equiv, old_stage


def _acquire_medium_mag_at(scope:MicroscopeInterface, grid, stage_xyz, name:str, content:Dict):
    """Moves to stage_xyz and acquires a medium mag image, or a mini-montage covering
    ``content['n_pitches']`` (default 4) hole pitches. Returns the processed Montage."""
    from Smartscope.core.grid.run_io import get_file_and_process
    stage_x, stage_y, stage_z = stage_xyz
    scope.moveStage(stage_x, stage_y, stage_z=stage_z)
    num_tiles_x, num_tiles_y = scope.set_medium_mag_size_mini_montage(
        hole_pitch_um=grid.holeType.pitch, n_pitches=content.get('n_pitches', 4))
    im_file = f'raw/{name}.mrc'
    if max(num_tiles_x, num_tiles_y) == 1:
        scope.medium_mag_hole(file=im_file)
    else:
        scope.medium_mag_montage((num_tiles_x, num_tiles_y), file=im_file)
    return get_file_and_process(
        raw=im_file,
        name=name,
        directory=grid.session_id.microscope_id.scope_path,
        force_reprocess=True
    )


def find_square_junk_anchors(square, content:Dict=None, square_montage=None):
    """Finds anchors on the (pre-reload) square image for medium mag re-registration (v1 and v2).

    1. YOLO junk detection. With ``content['crop_to_square']`` (default True) detection runs on a
       crop of the illuminated part of the square, which gives the model more pixels on small or
       partially covered squares. Detections are always mapped back to full resolution,
       uncropped square image pixels before converting to stage coordinates.
       Detections below ``min_anchor_conf`` (default 0.2) are discarded. Ranking: confidence,
       then isolation from other detections.
    2. If no YOLO anchor is usable and ``content['structure_fallback']`` (default True), up to
       ``n_structure_anchors`` (default 3) model-free candidates are added: places with the
       strongest non-periodic structure after hole suppression (see ``find_structure_anchors``).

    Returns a list of dicts sorted best first, each with:
        square_px  : (x, y) full resolution square image pixel (uncropped)
        stage_xyz  : stage position of the anchor in the pre-reload frame (microns)
        source     : 'yolo' or 'structure'
        confidence : YOLO confidence (None for structure anchors or if the AI worker does not
                     return it)
        score      : structure score (structure anchors only)
        isolation_pitches : distance to the nearest other YOLO detection, in hole pitches
    """
    from Smartscope.lib.image.montage import Montage
    from Smartscope.lib.image.target import Target
    from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast, auto_contrast_sigma, to_8bits
    from Smartscope.tasks.base_tasks import send_find_junk
    from Smartscope.core.reregistration.xcorr_register import (
        illuminated_mask, square_crop_box, find_structure_anchors)

    content = content or {}
    final_height = content.get('final_height', 1024)
    if square_montage is None:
        square_montage = Montage(square.name, working_dir=square.working_dir)
        square_montage.load_or_process()
    image = square_montage.image
    h, w = image.shape[:2]
    pitch_px = square.grid_id.holeType.pitch * 1e4 / square_montage.pixel_size

    mask = illuminated_mask(image)
    if content.get('crop_to_square', True):
        x0, y0, side = square_crop_box(mask)
    else:
        x0, y0, side = 0, 0, min(h, w)
    crop = image[y0:y0 + side, x0:x0 + side] if content.get('crop_to_square', True) else image
    scale = final_height / crop.shape[0]
    logger.debug(f'Junk detection on {square}: crop origin ({x0}, {y0}), size {crop.shape}, binning scale {scale:.3f}')

    normalizations = {'auto_contrast': auto_contrast, 'auto_contrast_sigma': auto_contrast_sigma, 'none': to_8bits}
    square_img = convert_to_png(crop, height=final_height,
                                normalization=normalizations[content.get('square_normalization', 'auto_contrast')])
    detections, confidences = send_find_junk(
        square_img,
        weights=content.get('weights_square', 'junk_detection/junk_square_norm.pt'),
        imgsz=content.get('imgsz', final_height),
        conf_thres=content.get('conf_thres_square', 0.1),
        iou_thres=content.get('iou_thres', 0.45),
        classes=content.get('classes_square', None),
        return_confidence=True,
    )
    # binned crop pixels -> full resolution, uncropped square pixels
    detections = detections / scale + np.array([x0, y0], dtype=float) if len(detections) else detections

    min_conf = content.get('min_anchor_conf', 0.2)
    if content.get('xcorr_mode', 'full') == 'anchor_patch':
        margin_px = content.get('patch_pitch', 0.75) * pitch_px + 2
    else:
        margin_px = 0.0  # the search window is padded where it extends beyond the square image

    def to_stage(p):
        t = Target(np.asarray(p, dtype=float), from_center=True)
        t.convert_image_coords_to_stage(square_montage)
        return (float(t.stage_x), float(t.stage_y), float(square_montage.stage_z))

    anchors = []
    for i, p in enumerate(detections):
        conf = float(confidences[i]) if confidences is not None else None
        if conf is not None and conf < min_conf:
            logger.debug(f'Junk at {np.round(p, 1)} below minimum anchor confidence ({conf:.2f} < {min_conf}), skipping.')
            continue
        if not (margin_px <= p[0] <= w - margin_px and margin_px <= p[1] <= h - margin_px):
            logger.debug(f'Junk at {np.round(p, 1)} too close to the square image border, skipping.')
            continue
        others = np.delete(detections, i, axis=0)
        isolation = np.min(np.linalg.norm(others - p, axis=1)) / pitch_px if len(others) else np.inf
        anchors.append(dict(square_px=np.asarray(p, dtype=float), source='yolo', confidence=conf,
                            score=None, isolation_pitches=float(isolation), stage_xyz=to_stage(p)))
    anchors.sort(key=lambda a: (-(a['confidence'] if a['confidence'] is not None else 0.0),
                                -min(a['isolation_pitches'], 3.0)))

    if not anchors and content.get('structure_fallback', True):
        candidates = find_structure_anchors(
            image, pitch_px, n=content.get('n_structure_anchors', 3),
            separation_px=content.get('n_pitches', 8) / 2 * pitch_px, mask=mask)
        logger.info(f'No usable YOLO anchor on {square}; using {len(candidates)} structure-based anchor(s).')
        for x, y, sc in candidates:
            anchors.append(dict(square_px=np.array([x, y]), source='structure', confidence=None,
                                score=sc, isolation_pitches=float('inf'), stage_xyz=to_stage((x, y))))

    def describe(a):
        quality = f"conf={a['confidence']:.2f}" if a['confidence'] is not None else (
            f"score={a['score']:.1f}" if a['score'] is not None else 'conf=n/a')
        return f"{a['source']} px={np.round(a['square_px'], 1)} {quality} stage={np.round(a['stage_xyz'][:2], 2)}"
    if anchors:
        logger.info(f'Found {len(anchors)} anchor(s) on {square}: ' + ', '.join(describe(a) for a in anchors))
    else:
        logger.info(f'No anchor found on {square}.')
    return anchors


def register_medium_to_square_xcorr(square, medium_montage, expected_px, old_stage, content:Dict=None,
                                    diagnostics_dir=None, name:str=None, square_montage=None, anchor_px=None,
                                    return_result:bool=False):
    """[v2] Locates a medium mag image in the original square image by cross-correlation.
    ``expected_px`` is the full resolution square pixel where the medium image center was
    targeted in the pre-reload frame.

    Modes (``content['xcorr_mode']``):
        'full' (default): the whole medium image, scaled and rotated from the image metadata, is
            the template; it is searched for in a square image window centered on ``expected_px``
            (the junk anchor) and larger than the medium field of view by ``max_shift_pitches``
            on each side.
        'anchor_patch': a small square patch around ``anchor_px`` is searched for inside the
            medium image.

    Returns (old_equiv, new): ``new`` is ``old_stage`` (where the image was acquired) and
    ``old_equiv`` is the pre-reload stage position of what was actually imaged. None if the
    correlation was ambiguous or weak.
    """
    from pathlib import Path
    from Smartscope.lib.image.montage import Montage
    from Smartscope.lib.image.target import Target
    from Smartscope.core.reregistration.xcorr_register import register_xcorr, locate_anchor_in_medium, save_diagnostics

    content = content or {}
    if square_montage is None:
        square_montage = Montage(square.name, working_dir=square.working_dir)
        square_montage.load_or_process()
    pitch_um = square.grid_id.holeType.pitch
    max_shift_um = content.get('max_shift_um', content.get('max_shift_pitches', 4) * pitch_um)

    mode = content.get('xcorr_mode', 'full')
    if mode == 'anchor_patch':
        if anchor_px is None:
            anchor_px = expected_px  # the medium image was acquired at the anchor
        result = locate_anchor_in_medium(
            medium_montage.image, medium_montage.pixel_size, medium_montage.rotation_angle,
            square_montage.image, square_montage.pixel_size, square_montage.rotation_angle,
            anchor_px=anchor_px, expected_px=expected_px, pitch_um=pitch_um,
            patch_pitch=content.get('patch_pitch', 0.75), lowpass_pitch=content.get('lowpass_pitch', 0.1),
            max_shift_pitches=content.get('max_shift_pitches', 4.0),
            medium_valid=getattr(medium_montage, 'valid_mask', None),
            medium_center_px=getattr(medium_montage, 'center_px', None),
            min_ncc=content.get('min_ncc', 0.2), min_margin=content.get('min_margin', 0.05),
        )
    else:
        result = register_xcorr(
            medium_montage.image, medium_montage.pixel_size, medium_montage.rotation_angle,
            square_montage.image, square_montage.pixel_size, square_montage.rotation_angle,
            expected_px=expected_px, pitch_um=pitch_um, max_shift_um=max_shift_um,
            min_ncc=content.get('min_ncc', 0.3), min_margin=content.get('min_margin', 0.05),
            suppress=content.get('suppress_holes', True), dilate_px=content.get('dilate_px', 1),
            lowpass_pitch=content.get('lowpass_pitch', 0.1),
            medium_center_px=getattr(medium_montage, 'center_px', None),
            refine=content.get('refine', False),
            refine_radius_pitch=content.get('refine_radius_pitch', 0.4),
            refine_lowpass_pitch=content.get('refine_lowpass_pitch', 0.02),
            local_threshold=content.get('local_hole_threshold', False),
        )
    name = name or medium_montage.name
    logger.info(
        f'Cross-correlation ({mode}) re-registration {name} on {square}: shift={np.round(result["shift_px"], 2)} px '
        f'({result["shift_pitches"]:.2f} pitch), peak={result["peak"]:.3f}, second={result["second_peak"]:.3f}, '
        f'margin={result["margin"]:.3f}, accepted={result["accepted"]}'
    )
    if result.get('refinement') is not None:
        ref = result['refinement']
        logger.info(f'Refinement {"used" if ref["used"] else "NOT used (peak on search boundary)"}: '
                    f'correction {np.round(ref["correction_px"], 2)} px, peak {ref["peak"]:.3f}')
    if diagnostics_dir is not None:
        try:
            Path(diagnostics_dir).mkdir(parents=True, exist_ok=True)
            save_diagnostics(result, Path(diagnostics_dir, f'{name}_xcorr.png'))
        except Exception as err:
            logger.warning(f'Could not save cross-correlation diagnostics for {name}: {err}')

    if not result['accepted']:
        logger.warning(f'Cross-correlation re-registration of {name} rejected (weak or ambiguous peak).')
        return (None, result) if return_result else None

    t_found = Target(result['found_px'], from_center=True)
    t_found.convert_image_coords_to_stage(square_montage)
    t_exp = Target(np.asarray(expected_px, dtype=float), from_center=True)
    t_exp.convert_image_coords_to_stage(square_montage)
    delta = t_found.stage_coords - t_exp.stage_coords
    old_stage = np.asarray(old_stage[:2], dtype=float)
    old_equiv = old_stage + delta
    logger.info(f'Re-registration pair for {name}: old={np.round(old_equiv, 3)}, new={np.round(old_stage, 3)} '
                f'(stage delta {np.round(delta, 3)} um)')
    if return_result:
        return (old_equiv, old_stage), result
    return old_equiv, old_stage


def _reregister_square_at_anchor(scope:MicroscopeInterface, square, content:Dict, prefix:str, register_fn):
    """Shared driver of the medium mag re-registration commands.

    Picks an anchor on the original square image (``content['anchor']`` or the best of
    find_square_junk_anchors), moves to its pre-reload stage position, acquires a medium mag
    image/mini-montage of ``n_pitches`` (default 8) hole pitches and hands it to ``register_fn``
    (register_medium_to_square or register_medium_to_square_xcorr).
    Returns an (old, new) stage coordinate pair or None.
    """
    from pathlib import Path
    from Smartscope.lib.image.montage import Montage
    content = content or {}
    grid = square.grid_id
    square_montage = Montage(square.name, working_dir=square.working_dir)
    square_montage.load_or_process()

    anchor = content.get('anchor')
    if anchor is None:
        anchors = find_square_junk_anchors(square, content, square_montage=square_montage)
        if not anchors:
            return None
        anchor = anchors[0]
    name = f'{prefix}_{square.pk}'
    # The field of view must cover the expected reload shift around the anchor
    acq_content = {**content, 'n_pitches': content.get('n_pitches', 8)}
    medium_montage = _acquire_medium_mag_at(scope, grid, anchor['stage_xyz'], name=name, content=acq_content)
    return register_fn(
        square, medium_montage, expected_px=anchor['square_px'], old_stage=anchor['stage_xyz'],
        content=content, diagnostics_dir=Path(grid.directory, 'reregistration'), name=name,
        square_montage=square_montage,
    )


def reregisterMediumMagFiducial(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    """[v1, method 'yolo'] Re-registers a square after grid reloading without going back to low mag.

    Images a junk anchor of the square at medium mag and registers the image onto the original
    square image by matching YOLO junk detections on both images.
    Returns an (old, new) stage coordinate pair or None.
    """
    return _reregister_square_at_anchor(scope, instance, content, 'reregister_fiducial', register_medium_to_square)


def reregisterMediumMagJunkXcorr(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    """[v2, method 'junk_xcorr'] Re-registers a square after grid reloading without going back to low mag.

    Images a junk anchor of the square at medium mag and locates the image in the original
    square image by hole-suppressed cross-correlation.
    Returns an (old, new) stage coordinate pair or None.
    """
    return _reregister_square_at_anchor(scope, instance, content, 'reregister_xcorr', register_medium_to_square_xcorr)


def delay(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    delay = content.get('delay', 1)
    units = content.get('units', 's')
    logger.info(f'Delaying for {delay} {units}')
    scope.delay(delay, units)


def reregisterSearchMag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    finder = instance.finders.order_by('-created_at').first()
    stage_x = finder.stage_x
    stage_y = finder.stage_y

    moveStage(scope,params,instance, content, *args, **kwargs)
    shift = scope.find_square_center_microns()
    shift = (stage_x + shift[0], stage_y + shift[1])
    logger.info(f'Reregistered search mag to {shift[0]:.2f}, {shift[1]:.2f}')
    scope.zero_image_shift()
    return shift

def openColumnValve(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    scope.open_valves()

def setupSerialEM(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    scope.setup_serialem()

def refineEucentricityByFocus(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    from Smartscope.core.models.target_label import Finder
    square = instance.square_id
    if not square.eucentricity_refined:
        moveStage(scope,params,square, content, *args, **kwargs)
        if not scope.autofocus_by_z():
            logger.warning('Autofocus by Z did not converge, falling back to regular eucentricity.')
            scope.eucentricity()
        holes = square.holemodel_set(manager='just_holes').filter(square_id=square.square_id).values_list('hole_id', flat=True)
        scope.logger.debug(f'Refined eucentricity for square {square.name} and updating the stage Z {len(holes)} holes.')
        Finder.objects.filter(object_id__in=holes).update(stage_z=scope.report_stage()[2])
        square.eucentricity_refined = True
        square.save()
    return instance.refresh_from_db()

def eucentricSearchAfterDistance(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    distance = content.get('distance', 300)
    method = content.get('method', 'eucentricHeight')
    if scope.microscope.narrowGapPolepiece:
        logger.info('Narrow gap polepiece detected, using eucentricity by focus instead of stage tilt.')
        method = 'eucentricity_by_focus'
    scope.eucentric_height_after_distance(distance_threshold=distance, method=method)

protocolCommandsFactory = dict(
    setAtlasOptics=setAtlasOptics,
    setAtlasOpticsDelay=setAtlasOpticsDelay,
    setAtlasOpticsImagingState=setAtlasOpticsImagingState,
    removeSlit=removeSlit,
    resetStage=resetStage,
    call=call,
    callFunction=callFunction,
    atlas=atlas,
    atlasInLowDoseSearch=atlasInLowDoseSearch,
    realignToSquare=realignToSquare,
    square=square,
    squareInMediumMag=squareInMediumMag,
    moveStage=moveStage,
    moveStageWithAtlasToSearchOffset=moveStageWithAtlasToSearchOffset,
    eucentricSearch=eucentricSearch,
    eucentricMediumMag=eucentricMediumMag,
    createHoleRef=createHoleRef,
    eucentricByBeamTilt=eucentricByBeamTilt,
    mediumMagHole=mediumMagHole,
    tiltToAngle=tiltToAngle,
    alignToHoleRef=alignToHoleRef,
    alignToHoleNoTemplate=alignToHoleNoTemplate,
    loadHoleRef=loadHoleRef,
    setHighMagOptics=setHighMagOptics,
    setSquareMagOptics=setSquareMagOptics,
    setMediumMagOptics=setMediumMagOptics,
    highMag=highMag,
    setFocusPosition=setFocusPosition,
    setAperturesForHighMag=set_apertures_for_highmag,
    setAperturesForLowMag=set_apertures_for_lowmag,
    refineOpticsForHighMag=refineOpticsForHighMag,
    autoFocus=autoFocus,
    autoFocusAfterDistance=autoFocusAfterDistance,
    waitDrift=waitDrift,
    zeroImageShift=zeroImageShift,
    rollDefocus=rollDefocus,
    autofocusByZ=autofocusByZ,
    loadGrid=loadGrid,
    unloadGrid=unloadGrid,
    setHighmagCountingMode=setHighmagCountingMode,
    resetAFISimageShift=resetAFISimageShift,
    setAFISimageShift=setAFISimageShift,
    refineZLP=refineZLP,
    collectHardwareDark=collectHardwareDark,
    flashColdFEG=flashColdFEG,
    recenterBeam=recenterBeam,
    setupFrames=setupFrames,
    resetState=resetState,
    reregisterMediumMag=reregisterMediumMag,
    reregisterSearchMag=reregisterSearchMag,
    reregisterMediumMagFiducial=reregisterMediumMagFiducial,
    reregisterMediumMagJunkXcorr=reregisterMediumMagJunkXcorr,
    openColumnValve=openColumnValve,   
    callOnModeChange=callOnModeChange, 
    setupSerialEM=setupSerialEM,
    setupApertures=setupApertures,
    refineEucentricityByFocus=refineEucentricityByFocus,
    eucentricSearchAfterDistance=eucentricSearchAfterDistance,
    findHoleGeometry=findHoleGeometry,
)