from pprint import pformat
import numpy as np
import logging
from scipy.spatial.distance import cdist
from scipy.spatial import KDTree
from scipy.optimize import linear_sum_assignment
from Smartscope.lib.image.process_image import ProcessImage


logger = logging.getLogger(__name__)

def register_to_other_montage(
        coords,
        center_coords,
        montage,
        parent_montage,
        extra_angle=0
    ):
    centered_coords =  coords - center_coords
    scale = parent_montage.pixel_size / montage.pixel_size
    scaled_coords = centered_coords * scale 
    delta_rotation = parent_montage.rotation_angle - montage.rotation_angle + extra_angle
    logger.debug(f'''
        Image Rotation = {montage.rotation_angle}
        Parent Rotation = {parent_montage.rotation_angle}
        Delta = {parent_montage.rotation_angle - montage.rotation_angle}
        Currently testing = {delta_rotation}
    ''')
    pixel_coords = np.apply_along_axis(ProcessImage.rotate_axis, 1,
        scaled_coords, angle=delta_rotation)
    centered_pixel_coords = pixel_coords + montage.center
    return centered_pixel_coords

def register_to_other_montage_from_vectors(stage_coords,center_stage_coords,montage):
    centered_stage_coords = stage_coords - center_stage_coords
    recentered_stage_coords = centered_stage_coords + np.array(montage.metadata.iloc[-1].StagePosition)
    logger.debug(f'Rencentered stage coordinates: {recentered_stage_coords}. \nShape: {recentered_stage_coords.shape}')
    pixel_coords = np.apply_along_axis(ProcessImage.pixel_to_stage_from_vectors,1, recentered_stage_coords, montage.metadata.iloc[-1].StageToImageMatrix)
    pixel_coords[:, 1] = montage.shape_x - pixel_coords[:, 1]  #np.array([pixel_coords[:,0],montage.shape_x - pixel_coords[:,1]])
    return pixel_coords
    

def register_stage_to_montage(
        targets_stage_coords:np.ndarray,
        center_stage_coords:np.ndarray,
        center_pixel_coords:np.ndarray,
        apix:float,
        rotation_angle:float
    ):
    """Converts stage coordinates calculated at a given magnification to another magnification image. 
    i.e. Draw holes found at low SA on the Atlas or vice-versa

    Args:
        targets_stage_coords (np.ndarray): 2-D array of stage or specimen x,y coordinates in microns where each line is a coordinate pair
        center_stage_coords (np.ndarray): x,y stage or specimen coordinates of the image where the targets are to be registered
        center_pixel_coords (np.ndarray): x,y pixel coordinates of the center_stage_coords argument
        apix (float): Pixel size in Angstrom per pixel of the image where the targets are being registered
        rotation_angle (float): Rotation angle of the tilt axis of the image where the targets are being registered
    """
    centered_stage_coords = targets_stage_coords - center_stage_coords
    stage_pixel_coords = np.array(centered_stage_coords) / (apix/10_000)
    pixel_coords = np.apply_along_axis(ProcessImage.rotate_axis, 1,
        stage_pixel_coords, angle=rotation_angle)
    centered_pixel_coords = pixel_coords + center_pixel_coords
    return centered_pixel_coords


def closest_to_center(
        coords:np.ndarray,
        center_coords:np.ndarray
    ) -> int: 
    """Finds the closest coordinate to a center coordinate

    Args:
        coords (np.ndarray): 2-D array of x,y coordinates where each line is a coordinate pair
        center_coords (np.ndarray): x,y coordinates of the center

    Returns:
        int: Index of the closest coordinate
    """
    centered_coords = coords - center_coords
    distance = np.sqrt(np.sum(np.power(centered_coords,2),axis=1))
    return np.argmin(distance)

def recenter_targets(
        coords:np.ndarray,
        center_coords:np.ndarray
        ) -> np.ndarray:
    closest_to_center_index = closest_to_center(coords, center_coords)
    return coords - (coords[closest_to_center_index] - center_coords)

# def rotate_axis(coord, angle):
#     theta = np.radians(angle)
#     c, s = np.cos(theta), np.sin(theta)
#     R = np.array(((c, -s), (s, c)))
#     rotated = np.sum(R * np.reshape(coord, (-1, 1)), axis=0)
#     return rotated
# def find_values_by_uniqueness(array: np.ndarray):
#     """Split an array into unique and non-unique values"""
#     # Get unique values and their counts
#     unique_values, counts = np.unique(array, return_counts=True)
#     # Select values that appear only once
#     values_appear_once = unique_values[counts == 1]
#     values_appear_more_than_once = unique_values[counts > 1]
#     return values_appear_once, values_appear_more_than_once

# def unassign_target(distance_matrix,closest_index, non_unique_values):
#     for value in non_unique_values:
#         indices_to_check = np.argwhere(closest_index == value).flatten()
#         # pruned_distance_matrix = distance_matrix[indices_to_check]
#         # idx = np.argmin(distance_matrix[indices_to_check,value])
#         idx = indices_to_check[np.argmin(distance_matrix[indices_to_check, value])]

#         logger.info(f'Keeping target {idx}. Unassigning the rest assigned to {value}')
#         mask = (closest_index == value) & (np.arange(len(closest_index)) != idx)
#         closest_index[mask]= -1
#     logger.info(f'Closest index: {closest_index}')
#     return closest_index


# def assing_last_indexes(distance_matrix,initial_distance_matrix):
#     rows_all_inf = np.all(distance_matrix == np.inf, axis=1)
#     cols_all_inf = np.all(distance_matrix == np.inf, axis=0)
#     row_indices = np.where(rows_all_inf)[0]
#     col_indices = np.where(cols_all_inf)[0]
#     for row_index in row_indices:
#         for col_index in col_indices:
#             distance_matrix[row_index,col_index] = initial_distance_matrix[row_index,col_index]
#     return np.argmin(distance_matrix,1)

# def reassign_targets(distance_matrix,closest_index, loop=0, initial_distance_matrix=None):
#     if loop == 0:
#         initial_distance_matrix = distance_matrix.copy()
#     np.set_printoptions(precision=3)
#     if loop > distance_matrix.shape[1]*2:
#         raise ValueError('Loop limit reached, Please report this bug.')
    
#     sorted_indices = np.argsort(distance_matrix, axis=1)
#     logger.info(f'Sorted indices: \n{sorted_indices}')
#     unique_values, non_unique_values = find_values_by_uniqueness(closest_index)
#     unassigned_values = set(range(distance_matrix.shape[1])) - set(closest_index)
    
#     if len(unassigned_values) == 0:
#         logger.warning(f"It seems like there are no unassigned values but there are still multiple targets assigned to the same hole. Will unassign the farthest target. Loop: {loop}")
#         return unassign_target(distance_matrix,closest_index, non_unique_values)
#     logger.info(f'Unique values: {unique_values}, Non-unique values: {non_unique_values}, Unassigned values: {unassigned_values}')

#     new_closest_index = closest_index.copy()

#     for value in non_unique_values:
#         rows_to_check = np.argwhere(closest_index == value).flatten()
#         logger.debug(f'Rows to check: {rows_to_check}')
#         check_column = 1
#         unassigned_new = unassigned_values.copy()
#         for unassigned in unassigned_values:
#             rows_where_unassigned = np.argwhere(sorted_indices[:,check_column] == unassigned).flatten()
#             next_closests = np.intersect1d(rows_to_check, rows_where_unassigned)
#             logger.debug(f'Next closests: {next_closests}')
#             if len(next_closests) == 0:
#                 logger.debug(f'No next closests for {unassigned}')
#                 continue
#             if len(next_closests) == 1:
#                 idx = next_closests[0]
#                 logger.info(f'Assiging index {idx} to {unassigned}')
#                 new_closest_index[idx] = unassigned
#                 unassigned_new.remove(unassigned)
#                 break
#             idx = rows_to_check[np.argmin(distance_matrix[rows_to_check, unassigned])]
#             logger.info(f'Assiging index {idx} to {unassigned}')
#             new_closest_index[idx] = unassigned
#             unassigned_new.remove(unassigned)
#         if len(unassigned_new) == 0:
#             break

#         # for i, row in enumerate(sorted_indices):
#         #     # logger.debug(row)
#         #     if value == row[0]:
#         #         if row[1] in unassigned_values:
#         #             new_closest_index[i] = row[1]
#         # idx = np.argmin(distance_matrix[:,value])
#         # # distance_matrix[:,value] = np.inf
#         # if not 0 in distance_matrix[idx]:
#         #     distance_matrix[idx,value] = 0
#     # for value in unassigned_values:
#     #     idx = np.argmin(distance_matrix[:,value])
#     #     # distance_matrix[:,value] = np.inf
#     #     if not 0 in distance_matrix[idx]:
#     #         distance_matrix[idx,value] = 0


  

#     logger.debug(f'Distance matrix:\n {distance_matrix}')
#     # new_closest_index = np.argmin(distance_matrix,1)
#     if (new_closest_index == closest_index).all():
#         logger.warning('No change in assignment. Checking which target is closest to unassigned.')
#         for unassigned in unassigned_values:
#             idx = np.argmin(distance_matrix[:,unassigned])
#             logger.info(f'Closest target to {unassigned} is {idx}')
#             new_closest_index[idx] = unassigned
#     logger.info(f'Closest index: {new_closest_index}')
#     if len(new_closest_index) == len(set(new_closest_index)):
#         logger.info(f'All targets have been assigned to a unique hole. Loop: {loop}')
#         return new_closest_index
#     logger.warning('There are multiple targets assigned to the same hole. Running another loop.')
#     return reassign_targets(distance_matrix,new_closest_index, loop=loop+1, initial_distance_matrix=initial_distance_matrix)
def filter_Y_based_on_X(X, Y):
    """
    Remove points in Y that are farther than the maximum distance from X's center.
    """
    # Compute center of X
    # X_center = np.mean(X, axis=0)
    
    # Compute distances of X points from the center
    X_distances = np.linalg.norm(X, axis=1)
    
    # Maximum distance in X
    max_X_distance = np.max(X_distances)
    
    # Compute distances of Y points from the X center
    # Y_center = np.mean(X, axis=0)
    Y_distances = np.linalg.norm(Y, axis=1)
    idxs = np.linspace(0,len(Y)-1,len(Y),dtype=int)

    
    logger.debug(f'Max X_distance:{max_X_distance}, Max Y_distance:{np.max(Y_distances)}, idxs:{idxs}')
    
    # Filter Y to keep only points within the max distance of X
    Y_filtered = Y[Y_distances <= max_X_distance*1.2]
    idx_filtered = idxs[Y_distances <= max_X_distance*1.2]
    assert len(Y_filtered) == len(idx_filtered)

    logger.debug(f'Max radius from new points: {max_X_distance} (Threshold:{max_X_distance*1.1}), removed {len(Y) - len(Y_filtered)} points that were too far away') 
    
    return Y_filtered, idx_filtered

def register_targets_by_proximity(X, Y):
    """
    Find closest points in Y for each point in X using KDTree.
    """
    X = np.asarray(X)
    Y = np.asarray(Y)
    logger.debug(f'length of X: {len(X)}, length of Y: {len(Y)}')
    X_filteted, indices = filter_Y_based_on_X(Y,X)
    distances = np.linalg.norm(X_filteted[:, None] - Y[None, :], axis=2)

    # Solve the assignment problem
    row_indices, col_indices = linear_sum_assignment(distances)
    logger.debug(f"Row indices: {row_indices} {len(row_indices)}, Col indices: {col_indices} {len(col_indices)}")
    assingment=np.ones(X.shape[0]) * -1
    assingment = assingment.astype(int)
    for i, j in zip(row_indices, col_indices):
        assingment[indices[i]] = j
    logger.debug(f"Assignment: {assingment}")
    return assingment

# def register_targets_by_proximity(
#         targets:np.ndarray,
#         new_targets:np.ndarray,
#     ):
#     distance_matrix = cdist(targets,new_targets)
#     closest_index = np.argmin(distance_matrix,1)
#     logger.debug(f'Distance matrix:\n {pformat(distance_matrix)}')
#     logger.info(f'Closest index: {closest_index}')
#     if len(closest_index) == len(set(closest_index)):
#         logger.info('All targets have been assigned to a unique hole')
#         return closest_index
#     logger.warning('There are multiple targets assigned to the same hole. Re-assinging.')
#     return reassign_targets(distance_matrix,closest_index)


def estimate_transform(X, Y):
    X = np.asarray(X)
    Y = np.asarray(Y)
    # Center the data
    X_mean = np.mean(X, axis=0)
    Y_mean = np.mean(Y, axis=0)
    X_centered = X - X_mean
    Y_centered = Y - Y_mean

    # Compute scaling
    scale = np.linalg.norm(Y_centered) / np.linalg.norm(X_centered)

    # Compute rotation using SVD
    H = X_centered.T @ Y_centered
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T

    # Ensure a proper rotation (no reflection)
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    # Compute translation
    t = Y_mean - scale * (X_mean @ R)

    return scale, R, t
