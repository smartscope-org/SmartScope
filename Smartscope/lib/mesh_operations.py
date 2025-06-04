import numpy as np
import logging
from scipy.spatial.distance import cdist

logger = logging.getLogger(__name__)

def filter_closest(points,expected_dist, limit=0.2):

    distances = cdist(points,points)
    # logger.debug(f'Distance matrix for {points} = \n{distances}')
    out_points = []
    dists = []
    for ind,row in enumerate(distances):
        filter_argwhere = np.argwhere([row > expected_dist*(1-limit), row < expected_dist*(1+limit)])
        # logger.debug(f'Argwhere result for {row} = {filter_argwhere} ')
        indexes= [i[1] for i in filter_argwhere if i[0] ==1 and i[1] != ind]
        filtered = points[indexes,:] - points[ind]
        out_points.extend(filtered)
        dists.extend(row.copy()[indexes])
    return np.array(out_points), np.median(dists)

def generate_rotated_grid(spacing, angle, shape, offset=np.array([0,0])):
    # Generate a grid of points with spacing
    x = np.arange(-shape[1],shape[1], spacing)  # Adjust the range as needed
    y = np.arange(-shape[0],shape[0], spacing)
    xx, yy = np.meshgrid(x, y)

    # Flatten the grid of points
    points = np.vstack([xx.ravel(), yy.ravel()])

    # Define rotation matrix
    theta = np.radians(angle)
    c, s = np.cos(theta), np.sin(theta)
    rotation_matrix = np.array(((c, -s), (s, c)))

    # Rotate the points
    rotated_points = np.dot(rotation_matrix, points)

    coordinates = rotated_points + offset.reshape(2,1)

    return coordinates


def remove_indices(array, indices):
    # Create a boolean mask with True values for indices to remove
    mask = np.ones(len(array), dtype=bool)
    mask[indices] = False

    # Use boolean indexing to remove the specified indices
    result = array[mask]

    return result
    

def calculate_translation(lattice1, lattice2):
    # Calculate pairwise Euclidean distances between all points in the lattices
    distances = cdist(lattice1, lattice2)
    min_idx = np.argmin(distances,axis=1)
    # Find the indices of the minimum distance
    # min_index = np.unravel_index(np.argmin(distances,axis=1), distances.shape)
    # Calculate the translation based on the difference between the indices of minimum distance
    translation = lattice1 - lattice2[min_idx]

    return np.median(translation,axis=0), min_idx


def filter_oob(coordinates, shape):
    x_coords, y_coords = coordinates[:,0], coordinates[:,1]
    # print(x_coords, y_coords)
    # Create boolean masks for x and y coordinates within specified ranges
    x_mask = np.logical_and(x_coords >= 0, x_coords < shape[1])
    y_mask = np.logical_and(y_coords >= 0, y_coords < shape[0])

    # Use boolean indexing to filter coordinates based on the masks
    filtered_coordinates = coordinates[np.logical_and(x_mask, y_mask),:]

    return filtered_coordinates

def atan2_firstquad(point):
    angle = np.degrees(np.arctan2(point[1],point[0]))
    while angle > 90:
        angle-=90
    while angle < 0:
        angle += 90
    return angle

def get_average_angle(points):
    angles = np.apply_along_axis(atan2_firstquad,axis=1, arr=points)
    return np.mean(angles)


def get_mesh_rotation_spacing(targets, mesh_spacing_in_pixels):
    # grid = AutoloaderGrid.objects.get(pk=grid_id)
    # print(f'Finding points within {mesh_spacing_in_pixels} pixels.')
    filtered_points, spacing= filter_closest(targets, mesh_spacing_in_pixels)
    logger.debug(f'Calculated mean spacing: {spacing} pixels')
    rotation = get_average_angle(filtered_points)
    logger.debug(f'Calculated mesh rotation: {rotation} degrees')
    return rotation, spacing

def closest_to_center(points:np.ndarray,center:np.ndarray):
    coords_from_center = points - np.array(center)
    dist_to_center = np.sqrt(np.sum(np.power(coords_from_center,2),axis=1))
    return np.argmin(dist_to_center)

def filter_from_center(points, center_point, radius_in_pixel):
    distances = cdist(points,[center_point])
    # logger.debug(f'Distance matrix for {points} = \n{distances}')
    logger.debug(f'Filtering points under {radius_in_pixel} pixels from center point.')
    indexes = np.argwhere(distances < radius_in_pixel)
    logger.debug(f'Filtered indexes {len(indexes)} from {len(points)} points')
    return points[indexes[:,0],:]