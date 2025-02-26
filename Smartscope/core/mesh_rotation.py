import numpy as np
import logging
from typing import Callable
from Smartscope.core.models import AutoloaderGrid, SquareModel, HoleModel
from Smartscope.lib.Datatypes.grid_geometry import GridGeometry, GridGeometryLevel
from Smartscope.lib.mesh_operations import filter_closest, get_average_angle, get_mesh_rotation_spacing
# from scipy.spatial import KDTree
# from scipy.signal import correlate2d
from itertools import groupby
from operator import itemgetter


logger = logging.getLogger(__name__)

def create_basic_mesh(spacing:float,size=10):
    a_range = np.arange(0, size, 1) *spacing 
    X, Y = np.meshgrid(a_range, a_range)
    points = np.vstack((X.ravel(), Y.ravel())).T
    return points


def hole_mesh(grid_instance):
    # square = SquareModel.display.filter(grid_id=grid_instance,status='completed').first()
    holes = HoleModel.display.filter(grid_id=grid_instance)
    holes = list(filter(lambda x: x.finders.all()[0].method_name != 'Regular pattern', holes))
    hole_spacing = grid_instance.holeType.pitch
    return holes, hole_spacing

def square_mesh(grid_instance):
    squares = SquareModel.display.filter(grid_id=grid_instance)
    square_spacing = grid_instance.meshSize.pitch
    return squares,square_spacing

def get_mesh_rotation(grid:AutoloaderGrid, level:Callable=hole_mesh, algo:Callable=get_average_angle):
    # grid = AutoloaderGrid.objects.get(pk=grid_id)
    targets, mesh_spacing = level(grid)
    stage_coords = np.array([t.stage_coords for t in targets])
    logger.debug(f'Found {len(targets)} targets. Mesh Spacing is {mesh_spacing} um.')
    filtered_points, _= filter_closest(stage_coords, mesh_spacing*1.08)
    rotation = algo(filtered_points)
    logger.debug(f'Calculated mesh rotation: {rotation}')
    return rotation



# def compute_fourier_transform(points, grid_size=512):
#     # Create an empty 2D grid to hold the points
#     grid = np.zeros((grid_size, grid_size))
    
#     # Map points to grid coordinates (you may need to normalize)
#     for p in points:
#         x, y = int(p[0]//(grid_size - 1)), int(p[1]//(grid_size - 1))
#         grid[x,y] = 1
    
#     # Compute 2D Fourier Transform and shift the zero frequency to the center
#     fft_result = fftshift(fft2(grid))
#     magnitude_spectrum = np.abs(fft_result)
#     return magnitude_spectrum

# def detect_grid_orientation_and_spacing(fft_magnitude, grid_size=512):
#     # Smooth the magnitude spectrum to remove noise
#     smoothed_spectrum = gaussian_filter(fft_magnitude, sigma=2)
    
#     # Find peaks in the smoothed spectrum
#     peaks = peak_local_max(smoothed_spectrum, min_distance=10)
    
#     # Compute the distance and orientation of the dominant peaks
#     center = np.array([grid_size // 2, grid_size // 2])
#     peak_distances = []
#     peak_angles = []
    
#     for peak in peaks:
#         dy, dx = peak - center
#         distance = np.hypot(dx, dy)
#         angle = np.arctan2(dy, dx)
#         peak_distances.append(distance)
#         peak_angles.append(angle)
    
#     # The dominant grid orientation and spacing
#     avg_angle = np.median(peak_angles)
#     avg_spacing = np.median(peak_distances)
    
#     return avg_spacing, avg_angle


def calculate_hole_geometry(grid:AutoloaderGrid):
    targets, mesh_spacing = hole_mesh(grid)
    pixel_size = targets[0].parent.pixel_size
    expected_spacing = mesh_spacing / pixel_size * 10_000
    logger.debug(f'Calculating hole geometry for grid {grid} with {len(targets)} holes and mesh spacing: {mesh_spacing} um. Pixel size of {targets[0].parent}: {pixel_size} A.')
    targets.sort(key=lambda x: x.parent.pk)
    grouped_items = []
    for _, group in groupby(targets, key=lambda x: x.parent.pk):
        grouped_items.append(np.array([t.coords for t in group]))
    logger.debug(f'Grouped items in {len(grouped_items)} groups.')
    rotations, spacings = [],[]
    for i, group in enumerate(grouped_items):
        if len(group) < 2:
            continue
        logger.debug(f'Calculating rotation and spacing for group {i} containing {len(group)} holes.')
        try:
            rotation, spacing = get_mesh_rotation_spacing(group, expected_spacing)
            rotations.append(rotation)
            spacings.append(spacing)
        except np.exceptions.AxisError:
            logger.debug(f'Skipping {group} because not enough hole close to each others.')
            continue
    logger.debug(f'Calculated rotations: {rotations} degrees and spacings: {spacings} pixels. Expected spacing: {expected_spacing:.2f} pixels.')
    rotation = np.mean(rotations)
    spacing = np.mean(spacings)

    
    geometry = GridGeometry.load(directory=grid.directory)
    geometry.set_geometry(level=GridGeometryLevel.SQUARE, spacing=spacing, rotation=rotation)
    geometry.save(directory=grid.directory)
    logger.info(f'Updated grid {grid} with rotation: {rotation} degrees and spacing: {spacing} pixels.')
    return rotation, spacing

def save_mm_geometry(grid:AutoloaderGrid):
    pass



# Example: compute and plot the Fourier spectrum
