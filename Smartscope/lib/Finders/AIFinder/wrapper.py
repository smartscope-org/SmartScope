import os
import sys
import cv2
from typing import Dict
import numpy as np
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'detectors'))

from .detectors.detect_squares import detect
from .detectors.detect_holes import detect_holes, detect_and_classify_holes
# from ..basic_finders import find_square_center
import logging
import torch

from Smartscope.lib.image.montage import Montage
from Smartscope.lib.mesh_operations import get_mesh_rotation_spacing, closest_to_center, filter_from_center
from Smartscope.lib.Finders.lattice_extension import generic_lattice_extension
from Smartscope.lib.image.targets import Targets

logger = logging.getLogger(__name__)

WEIGHT_DIR = os.path.join(os.getenv("TEMPLATE_FILES"), 'weights')
IS_CUDA = False if eval(os.getenv('FORCE_CPU')) else torch.cuda.is_available() 


def find_squares(montage, class_map:Dict=None, **kwargs):
    logger.info('Running AI find_squares')
    kwargs['weights'] = os.path.join(WEIGHT_DIR, kwargs['weights'])
    if not IS_CUDA:
        kwargs['device'] = 'cpu'
    squares, labels, _, _ = detect(montage.image, **kwargs)
    success = True
    if len(squares) < 20 and montage.image.shape[0] > 20000:
        success = False
    logger.info(f'AI square finder found {len(squares)} squares')
    logger.debug(f'{squares},{type(squares)}')
    squares = [i.numpy() for i in squares]
    return (squares, labels), success, dict()

def find_holes_from_image(image, class_map:Dict=None, success_threshold:int=10,  **kwargs):
   
    def filter_hole_class(hole):
        return class_map[hole[-1]].name == 'Hole'
    
    center = np.array([image.shape[1]/2, image.shape[0]//2],dtype=int)
    logger.info('Running AI hole detection')
    # centroid = find_square_center(montage.image)
    kwargs['weights_circle'] = os.path.join(WEIGHT_DIR, kwargs['weights_circle'])
    if not IS_CUDA:
        kwargs['device'] = 'cpu'
    
    all_targets = detect_holes(image, **kwargs)
    holes = list(filter(lambda x: filter_hole_class(x), all_targets))

    logger.info(f'AI hole detection found {len(holes)} holes')
    success = True
    if len(holes) < success_threshold:
        success = False
    logger.debug(f'{holes[0]},{type(holes[0])}')
    
    holes = [(np.array(hole[0:-1])-np.array(list(center)*2)) + np.array(list(center)*2) for hole in holes]
    # logger.debug(f'{holes[0]},{type(holes[0])}')
    return holes, success, dict()


def find_holes(montage:Montage, class_map:Dict=None, success_threshold:int=10,  **kwargs):
    return find_holes_from_image(montage.image, class_map, success_threshold, **kwargs)

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
    targets, success, _= find_holes(montage, class_map, success_threshold, **kwargs)
    if not success:
        return [], success, dict()
    targets = Targets.create_targets_from_box(targets, montage, force_mdoc=False) ###REPLACE WITH THE ENV VARIABLE
    expected_spacing = hole_spacing / montage.pixel_size_micron
    lattice_radius_in_pixels = lattice_radius / montage.pixel_size_micron * 1.2
    rotation, spacing = get_mesh_rotation_spacing(np.array([target.coords for target in targets]), expected_spacing)
    logger.debug(f'Calculated hole geometry for grid {montage} with {len(targets)} holes and mesh spacing: {spacing} um. Pixel size of {montage}: {montage.pixel_size} A.\n Calculated rotation: {rotation}\n Calculated spacing: {spacing}')
    lattice = generic_lattice_extension([t.coords for t in targets], np.array([lattice_radius_in_pixels,lattice_radius_in_pixels]), rotation, spacing, offset=montage.center)
    transposed = lattice.T
    logger.debug(f'Transposed lattice shape ({transposed.shape}):\n{transposed}')
    closest_lattice_point_to_center = closest_to_center(transposed, montage.center)
    filtered_lattice_from_center = filter_from_center(transposed, transposed[closest_lattice_point_to_center], lattice_radius_in_pixels)
    logger.debug(f'Extended lattice from {len(targets)} to {len(filtered_lattice_from_center)} holes using lattice extension\n{filtered_lattice_from_center}')
    # targets = Targets.create_targets_from_center(lattice, montage, force_mdoc=False,convert_to_stage=False) ###REPLACE WITH THE ENV VARIABLE
    return filtered_lattice_from_center, True, {'rotation': rotation, 'spacing': spacing}

    


def find_and_classify_holes(montage, **kwargs):
    logger.info('Running AI hole detection and classification')
    # centroid = find_square_center(montage.image)
    holes, labels = detect_and_classify_holes(montage.image, **kwargs)
    # print(holes)
    success = True
    if len(holes) < 20:
        success = False

    logger.info(f'AI hole detection found {len(holes)} holes')
    return (holes, labels), success, 'AIHoleTarget'
