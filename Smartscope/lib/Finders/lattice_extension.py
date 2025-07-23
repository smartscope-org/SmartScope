import numpy as np
import logging
from ..mesh_operations import generate_rotated_grid, calculate_translation, remove_indices, filter_oob
from .basic_finders import create_square_mask

logger = logging.getLogger(__name__)

def generic_lattice_extension(input_lattice:np.ndarray, diameter_in_pixels:np.ndarray, rotation:float, spacing:float, offset=np.array([0,0])):
    logger.debug(f'Generating lattice extension with spacing {spacing} and rotation {rotation} and diameter {diameter_in_pixels}')
    points = generate_rotated_grid(spacing, rotation, diameter_in_pixels, offset=offset)
    logger.debug(f'Generated {len(points)} points for lattice extension. Points go from x={np.min(points[0,:])} y={np.min(points[1,:])} to x={np.max(points[0,:])} y={np.max(points[0,:])}')
    translation, _ = calculate_translation(input_lattice,points.T)
    logger.debug(f'Calculated translation {translation}')
    translated = points + translation.reshape(2,-1)
    translation, min_idx = calculate_translation(input_lattice,translated.T)
    # translated = remove_indices(translated.T, min_idx)
    # translated = filter_oob(translated.T, diameter_in_pixels)
    translated = translated.astype(int)
    # mask = create_square_mask(image=input_lattice)
    # filtered = translated[np.where(mask[translated[:,1],translated[:,0]] == 1)]
    return translated
    # return filtered, True, dict(spacing=spacing, rotation=rotation, translation=translation)

def lattice_extension(input_lattice:np.ndarray, image:np.ndarray, rotation:float, spacing:float):
    translated = generic_lattice_extension(input_lattice, image.shape, rotation, spacing)
    points = generate_rotated_grid(spacing, rotation, image.shape)
    translation, _ = calculate_translation(input_lattice,points.T)
    translated = points + translation.reshape(2,-1)
    translation, min_idx = calculate_translation(input_lattice,translated.T)
    translated = remove_indices(translated.T, min_idx)
    translated = filter_oob(translated,image.shape)
    translated = translated.astype(int)
    mask = create_square_mask(image=image)
    filtered = translated[np.where(mask[translated[:,1],translated[:,0]] == 1)]
    return filtered
    # return filtered, True, dict(spacing=spacing, rotation=rotation, translation=translation)
