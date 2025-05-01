from celery.result import AsyncResult
import json
from typing import Dict
import logging
import numpy as np
from pydantic import BaseModel

from Smartscope.tasks.app import app
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.image_manipulations import encode_image
from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast_sigma, fourier_crop
from Smartscope.lib.mesh_operations import get_mesh_rotation_spacing, closest_to_center, filter_from_center
from Smartscope.lib.Finders.lattice_extension import generic_lattice_extension
from Smartscope.lib.image.targets import Targets

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

def send_find_squares_from_montage(montage, class_map:Dict[str,BaseModel], **kwargs):
    def class_map_to_yolo(class_map):
        yolo_class_map = dict()
        for k,v in class_map.items():
            class_name = v.label_training
            yolo_class_map[class_name] = k
        return yolo_class_map

    encoded = encode_image(montage.image)
    data = { 'image': encoded }
    data['kwargs'] = kwargs
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_squares', args=[json.dumps(data)], queue='celery')
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    coords, labels = res.get(interval=1, timeout=120)
    yolo_class_map = class_map_to_yolo(class_map=class_map)
    labels_converted =  [yolo_class_map[item] for item in labels]
    print(coords, labels_converted)
    return (coords,labels_converted), True, dict()

def send_find_holes_from_montage(montage:Montage, class_map:Dict[str,BaseModel], success_threshold:int=10,  **kwargs):
    scaling_factor = montage.image.shape[0] / 1024
    image= convert_to_png(montage.image, height=1024, normalization=auto_contrast_sigma, binning_method=fourier_crop)

    encoded = encode_image(image)

    data = { 'image': encoded }
    data['kwargs'] = kwargs
    data['kwargs']['scaling_factor'] = scaling_factor
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_holes', args=[json.dumps(data)], queue='celery')
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