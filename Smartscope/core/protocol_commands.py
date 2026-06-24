from typing import Dict
from random import random
import numpy as np
import logging
from Smartscope.core.interfaces.microscope_interface import MicroscopeInterface


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
    finder = instance.finders.first()
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
    scope.eucentricHeight()

def eucentricMediumMag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs) :
    """Calculates eucentricity using the View preset. Equivalent to Eucentric Rough."""
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
    pitch = grid.holeType.pitch
    num_tiles_x, num_tiles_y = scope.set_medium_mag_size_mini_montage(hole_pitch_um=pitch)
    im_file = 'raw/medium_mag_geometry.mrc'
    if max(num_tiles_x, num_tiles_y) == 1:
        scope.acquire_medium_mag(file=im_file)
    else:
        scope.medium_mag_montage((num_tiles_x, num_tiles_y), file=im_file)

    microscope_id = grid.session_id.microscope_id
    montage = get_file_and_process(
        raw=im_file,
        name='medium_mag_geometry',
        directory=microscope_id.scope_path,
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

def reregisterMediumMagFiducial(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    from Smartscope.core.grid.run_io import get_file_and_process
    grid = instance.grid_id
    pitch = grid.holeType.pitch
    num_tiles_x, num_tiles_y = scope.set_medium_mag_size_mini_montage(hole_pitch_um=pitch)
    im_file = f'raw/register_fiducial_{instance.pk}.mrc'
    if max(num_tiles_x, num_tiles_y) == 1:
        scope.acquire_medium_mag(file=im_file)
    else:
        scope.medium_mag_montage((num_tiles_x, num_tiles_y), file=im_file)

    microscope_id = grid.session_id.microscope_id
    montage = get_file_and_process(
        raw=im_file,
        name=f'medium_mag_fiducial_{instance.pk}',
        directory=microscope_id.scope_path,
        force_reprocess=True
    )
    ###NEED TO CONTINUE HERE.


def reregisterSearchMag(scope:MicroscopeInterface,params,instance, content:Dict, *args, **kwargs):
    finder = instance.finders.first()
    stage_x = finder.stage_x
    stage_y = finder.stage_y

    moveStage(scope,params,instance, content, *args, **kwargs)
    shift = scope.find_square_center_microns()
    return (stage_x + shift[0], stage_y + shift[1])

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
    scope.eucentric_height_after_distance(distance_threshold=distance)

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
    openColumnValve=openColumnValve,   
    callOnModeChange=callOnModeChange, 
    setupSerialEM=setupSerialEM,
    setupApertures=setupApertures,
    refineEucentricityByFocus=refineEucentricityByFocus,
    eucentricSearchAfterDistance=eucentricSearchAfterDistance
)