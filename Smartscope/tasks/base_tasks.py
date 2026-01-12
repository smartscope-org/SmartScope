from celery.result import AsyncResult
from celery.exceptions import TimeoutError
import json
from typing import Dict, Literal, List
import logging
import numpy as np
from pydantic import BaseModel
from pathlib import Path
from django.core.cache import cache

from Smartscope.tasks.app import app
from Smartscope.tasks.settings import QUEUES, TRANSIENT_QUEUES, TRANSIENT_QUEUES_CACHE_TIMEOUT
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.image_manipulations import encode_image
from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast_sigma, fourier_crop, auto_contrast, extract_box_from_radius
from Smartscope.lib.mesh_operations import get_mesh_rotation_spacing, closest_to_center, filter_from_center
from Smartscope.lib.Finders.lattice_extension import generic_lattice_extension
from Smartscope.lib.Finders.basic_finders import mask_square
from Smartscope.lib.image.targets import Targets

from Smartscope.sim_siam.prepare_data import sim_siam_prepare_data, sim_siam_copy_to_scratch_directory, sim_siam_copy_output_file_from_scratch, sim_siam_copy_output_directory_from_scratch, sim_siam_find_checkpoint
from Smartscope.sim_siam.models import SimSiamWeights, SimSiamTrainingProcess
from Smartscope.core.models import AutoloaderGrid

logger = logging.getLogger(__name__)

TEST_NOTIFICATION = """
{
"protocols": ["email"],
"notification_type": "error",
"title": "Test Notification",
"session_name": "Test Session",
"current_grid": "Test Grid",
"error_message": "Test Error line1\\nTest Error line2",
"email_list": ["bouvette@princeton.edu"]
}
"""

def get_queue()->str:
    for queue in QUEUES:
        if queue in TRANSIENT_QUEUES:
            cache_key = f'transient_queue_{queue}'
            in_use = cache.get(cache_key, False)
            if in_use:
                logger.info(f'Transient queue {queue} deemed availble from cache.')
                return queue

            res = app.send_task('SmartscopeAI.interfaces.celery.tasks.ping', queue=queue)
            try:
                _ = res.get(timeout=3, interval=0.1)
                cache.set(cache_key, True, timeout=TRANSIENT_QUEUES_CACHE_TIMEOUT)
                logger.info(f'Transient queue {queue} deemed availble from ping. Caching for {TRANSIENT_QUEUES_CACHE_TIMEOUT} seconds.')
                return queue
            except TimeoutError:
                
                logger.warning(f'Transient queue {queue} did not respond to ping, trying next queue.')
                continue
        return queue

def send_find_squares_from_montage(montage, class_map:Dict[str,BaseModel], **kwargs):
    def class_map_to_yolo(class_map):
        yolo_class_map = dict()
        for k,v in class_map.items():
            class_name = v.label_training
            yolo_class_map[class_name] = k
        return yolo_class_map
    
    scaling_factor = montage.image.shape[0] / kwargs.get('imgsz', 1024)
    image= convert_to_png(montage.image, height=kwargs.get('imgsz', 1024))

    encoded = encode_image(image)
    data = { 'image': encoded }
    data['kwargs'] = kwargs
    data['kwargs']['scaling_factor'] = scaling_factor
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_squares', args=[json.dumps(data)], queue=get_queue())
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    coords, labels = res.get(interval=1, timeout=120)
    yolo_class_map = class_map_to_yolo(class_map=class_map)
    labels_converted =  [yolo_class_map[item] for item in labels]
    print(coords, labels_converted)
    return (coords,labels_converted), True, dict()

def send_find_holes_from_montage(montage:Montage, class_map:Dict[str,BaseModel], success_threshold:int=10,  **kwargs):
    scaling_factor = montage.image.shape[0] / kwargs.get('imgsz', 1024)
    image= convert_to_png(montage.image, height=kwargs.get('imgsz', 1024), normalization=auto_contrast_sigma, binning_method=fourier_crop)

    encoded = encode_image(image)

    data = { 'image': encoded }
    data['kwargs'] = kwargs
    data['kwargs']['scaling_factor'] = scaling_factor
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_holes', args=[json.dumps(data)], queue=get_queue())
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
    return final_result, True, dict()

def send_find_holes_from_square(montage:Montage, class_map:Dict[str,BaseModel], success_threshold:int=10,  **kwargs):
    scaling_factor = montage.image.shape[0] / kwargs.get('imgsz', 1024)
    image= convert_to_png(montage.image, height=kwargs.get('imgsz', 1024), normalization=auto_contrast_sigma, binning_method=fourier_crop)
    image = mask_square(image)

    encoded = encode_image(image)

    data = { 'image': encoded }
    data['kwargs'] = kwargs
    data['kwargs']['scaling_factor'] = scaling_factor
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_holes', args=[json.dumps(data)], queue=get_queue())
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
    return final_result, True, dict()

def find_holes_with_lattice(montage, hole_spacing:float, lattice_radius:float, class_map:Dict=None, success_threshold:int=2, **kwargs):
    """
    Identifies holes in a montage image using a lattice pattern.
    Parameters:
    montage (ndarray): The montage image in which to find holes.
    class_map (Dict, optional): A dictionary mapping class labels to their respective values. Defaults to None.
    success_threshold (int, optional): The minimum number of successful detections required to consider the operation successful. Defaults to 10.
    hole_spacing (float): The spacing between holes in the lattice pattern in microns
    lattice_radius (float): The radius of the lattice used to find holes in microns.
    Returns:
    List[Tuple[int, int]]: A list of coordinates where holes were found.
    """
    targets, success, _= send_find_holes_from_montage(montage, class_map, success_threshold, **kwargs)
    if not success:
        return [], success, dict()
    targets = Targets.create_targets_from_box(targets, montage, force_mdoc=False) ###REPLACE WITH THE ENV VARIABLE
    expected_spacing = hole_spacing / montage.pixel_size_micron
    lattice_radius_in_pixels = lattice_radius / montage.pixel_size_micron
    rotation, spacing = get_mesh_rotation_spacing(np.array([target.coords for target in targets]), expected_spacing)
    logger.debug(f'Calculated hole geometry for grid {montage} with {len(targets)} holes and mesh spacing: {spacing} um. Pixel size of {montage}: {montage.pixel_size} A.\n Calculated rotation: {rotation}\n Calculated spacing: {spacing}')
    lattice = generic_lattice_extension([t.coords for t in targets], np.array([lattice_radius_in_pixels,lattice_radius_in_pixels]), rotation, spacing, offset=montage.center)
    transposed = lattice.T
    logger.debug(f'Transposed lattice shape ({transposed.shape}):\n{transposed}')
    closest_lattice_point_to_center = closest_to_center(transposed, montage.center)
    filtered_lattice_from_center = filter_from_center(transposed, transposed[closest_lattice_point_to_center], lattice_radius_in_pixels)
    logger.debug(f'Extended lattice from {len(targets)} to {len(filtered_lattice_from_center)} holes using lattice extension\n{filtered_lattice_from_center}')
    return filtered_lattice_from_center, True, {'rotation': rotation, 'spacing': spacing}

def sim_siam_inference(mag_level:Literal['square','hole'], grid_id:str, **kwargs):
    # Example usage

    """
    Sends a task to the Celery queue to process data for SimSiam training.
    Parameters:
    mag_level (Literal['square','hole']): The magnification level, either 'square' or 'hole'.
    grid_id (str): The ID of the grid to be processed.
    Returns:
    AsyncResult: The result of the Celery task.
    """
    if mag_level not in ['square','hole']:
        raise ValueError(f"Invalid magnification level: {mag_level}. Must be 'square' or 'hole'.")
    grid = AutoloaderGrid.objects.get(grid_id=grid_id)
    ####NEED TO ALSO TRANSFER THE CHECKPOINT AND CONFIGURATION IF AVAILABLE######

    checkpoint_path = None
    config_path = None

    weights = sim_siam_find_checkpoint(mag_level, grid)
    print(f'Found weights {weights} for mag level {mag_level} and grid {grid_id}')
    if weights is not None:
        training_process = SimSiamTrainingProcess.objects.filter(sim_siam_weights=weights).first()
        checkpoint_path = (weights.checkpoint_file,Path(*training_process.training_results_weights.parts[1:]))
        config_path = (weights.config_file, Path(*training_process.training_config_file.parts[1:]))

    grid_ids = [grid_id]  # Replace with actual grid IDs
    dataset_name = '_'.join(grid_ids) + "_" + mag_level
    file_list = sim_siam_prepare_data(mag_level, grid_ids)
    if checkpoint_path is not None and config_path is not None:
        file_list.append(checkpoint_path)
        file_list.append(config_path)

    sim_siam_copy_to_scratch_directory(dataset_name, file_list)

    data = json.dumps(dict(
        dataset_name = dataset_name,
        mag_level = mag_level,
        checkpoint_path = str(checkpoint_path)
    ))

    print(f'Sending SimSiam inference request for grid {grid_id} with magnification level {mag_level} and checkpoint {checkpoint_path}')
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.sim_siam_data', args=[data], queue=get_queue())
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
    
    sim_siam_copy_output_file_from_scratch(final_result, grid.directory)

def sim_siam_training(mag_level:Literal['square','hole'], grid_id:str, dataset_name=None,**kwargs):
    """
    Sends a task to the Celery queue to process data for SimSiam training.
    Parameters:
    mag_level (Literal['square','hole']): The magnification level, either 'square' or 'hole'.
    grid_id (str): The ID of the grid to be processed.
    Returns:
    AsyncResult: The result of the Celery task.
    """
    if mag_level not in ['square','hole']:
        raise ValueError(f"Invalid magnification level: {mag_level}. Must be 'square' or 'hole'.")
    grid = AutoloaderGrid.objects.get(grid_id=grid_id)

    checkpoint_path= Path(grid.directory) / f"model_best_{mag_level}.pth"
    if not checkpoint_path.is_file():
        checkpoint_path = None

    grid_ids = [grid_id]  # Replace with actual grid IDs
    if dataset_name is None:
        dataset_name = '_'.join(grid_ids) + "_" + mag_level
    file_list = sim_siam_prepare_data(mag_level, grid_ids)

    sim_siam_copy_to_scratch_directory(dataset_name, file_list)

    data = json.dumps(dict(
        dataset_name = dataset_name,
        mag_level = mag_level,
        checkpoint_path = str(checkpoint_path)
    ))
    print(f'Sending SimSiam inference request for grid {grid_id} with magnification level {mag_level} and checkpoint {checkpoint_path}')
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.sim_siam_training', args=[data], queue=get_queue())
    return result.id
    # res = AsyncResult(task_id, app=app)
    # final_result = res.get(interval=1, timeout=120)
    # print(final_result)
    
def sim_siam_check_task(task_id) -> AsyncResult:
    """
    Checks the status of a SimSiam task.
    Parameters:
    task_id (str): The ID of the task to check.
    Returns:
    str: The status of the task.
    """
    res = AsyncResult(task_id, app=app)
    return res
