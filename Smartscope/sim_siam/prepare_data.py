from typing import Dict, Literal, List
from pathlib import Path
import mrcfile
import cv2
from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast, extract_box_from_radius
from Smartscope.core.scratch import Scratch
from Smartscope.core.status import status
from Smartscope.core.models import AutoloaderGrid

from .models import SimSiamWeights, SimSiamTrainingProcess



def sim_siam_prepare_data(mag_level:Literal['square','hole'],grid_id_list:List[str],raise_on_empty:bool=True) -> List:
    extract_size_factor = 1.4
    if mag_level not in ['square','hole']:
        raise ValueError(f"Invalid magnification level: {mag_level}. Must be 'square' or 'hole'.")
    grid_id_list = AutoloaderGrid.objects.filter(grid_id__in=grid_id_list)
    
    if mag_level == 'square':
        from Smartscope.core.models import AtlasModel
        queryset = list(AtlasModel.objects.filter(grid_id__in=grid_id_list, status__in=[status.PROCESSED,status.COMPLETED]))
        if len(queryset) == 0:
            if raise_on_empty:
                raise ValueError(f"No data found for grid IDs: {grid_id_list} at magnification level {mag_level}.")
            return []
        
        item_sizes_microns = [grid.meshSize.square_size * extract_size_factor for grid in grid_id_list]
        if len(set(item_sizes_microns)) > 1:
            raise ValueError(f"All squares must have the same size, but found different sizes: {set(item_sizes_microns)}")
        filepath_attr = 'mrc'
        extract_size_pixel = 150

    elif mag_level == 'hole':
        from Smartscope.core.models import SquareModel
        queryset = list(SquareModel.display.filter(grid_id__in=grid_id_list, status__in=[status.PROCESSED,status.COMPLETED]))
        if len(queryset) == 0:
            raise ValueError(f"No data found for grid IDs: {grid_id_list} at magnification level {mag_level}.")
        item_sizes_microns = []
        for grid in grid_id_list:
            hole_size = grid.holeType.hole_size
            if hole_size is None:
                hole_size = 1.5
            item_sizes_microns.append(hole_size * extract_size_factor)
        if len(set(item_sizes_microns)) > 1:
            raise ValueError(f"All holes must have the same size, but found different sizes: {set(item_sizes_microns)}")
        filepath_attr = 'raw_mrc'
        extract_size_pixel = 50

    item_size_microns = item_sizes_microns[0] * extract_size_factor

    skipped = 0
    extracted = 0
    file_list = []
    print(f'Queryset contains {len(queryset)} items. {queryset}')
    for item in queryset:
        directory = item.directory
        image = getattr(item, filepath_attr)
        item_size_pixel = item_size_microns / (item.pixel_size /10_000)
        binning_factor = item_size_pixel / extract_size_pixel

        resized_image_path = Path(directory , f'sim_siam_{extract_size_pixel}.png')
        if not resized_image_path.is_file():
            print(f'Binned image not found, creating {resized_image_path}')
            with mrcfile.open(image) as mrc:
                img = mrc.data
            new_height = int(round(img.shape[0] / binning_factor))
            img = convert_to_png(img, height=new_height, normalization=auto_contrast)
            cv2.imwrite(resized_image_path, img)
        else:
            print(f'Binned image found, reading {resized_image_path}')
            img = cv2.imread(resized_image_path, cv2.IMREAD_UNCHANGED)

        extract_path = Path(directory, f'sim_siam_images')
        if not extract_path.is_dir():
            print(f'Creating extract directory {extract_path}')
            extract_path.mkdir(parents=True, exist_ok=True)
        print(f'Extracting {extract_size_pixel} pixel box from {resized_image_path}')
        radius = extract_size_pixel // 2
        for target in item.targets:
            image_file = extract_path / f'{target.pk}.jpg'
            file_list.append((image_file, Path('images', item.pk, image_file.name)))
            if image_file.is_file():
                skipped += 1
                continue
            finder = target.finders.first()
            x = int(round(finder.x/binning_factor))
            y = int(round(finder.y/binning_factor))
            boxed= extract_box_from_radius(img,x,y, radius)
            cv2.imwrite(image_file, boxed)
            extracted += 1
        print(f'Skipped {skipped} images, extracted {extracted} images from {resized_image_path}.')
    return file_list

def sim_siam_copy_to_scratch_directory(directory_name, file_list, scratch_dir=None) -> str:
    scratch = Scratch(max_size_gb=10, scratch=scratch_dir)
    # scratch.check_size(file_list, directory_name)
    return scratch.copy_to_scratch(file_list, directory_name)

def sim_siam_copy_output_file_from_scratch(file, output_directory, scratch_dir=None):
    scratch = Scratch(max_size_gb=10, scratch=scratch_dir)
    scratch.copy_file_from_scratch(Path(file), output_directory)

def sim_siam_copy_output_directory_from_scratch(directory_name, output_directory, scratch_dir=None):
    scratch = Scratch(max_size_gb=10, scratch=scratch_dir)
    scratch.copy_directory_from_scratch(Path(directory_name), output_directory)


def sim_siam_transfer_trained_model(process_id:str,scratch_dir=None):
    """
    Retrieve the trained SimSiam model based on the training process ID.
    Args:
        process_id (int): The ID of the training process.
    Returns:
        SimSiamWeights: The trained model weights.
    """
    training_process = SimSiamTrainingProcess.objects.filter(process_id=process_id).first()
    if training_process is None:
        raise ValueError(f"No training process found with ID {process_id}.")
    weights = training_process.sim_siam_weights
    if weights is None:
        raise ValueError(f"No trained weights found for training process ID {process_id}.")
    for file in [training_process.training_results_weights, training_process.training_config_file]:
        sim_siam_copy_output_file_from_scratch(file, weights.weights_directory, scratch_dir=scratch_dir)


def sim_siam_find_checkpoint(mag_level:Literal['square','hole'], grid:AutoloaderGrid) -> SimSiamWeights | None :
    """
    Find the SimSiam model weights for a given magnification level and grid.
    Args:
        mag_level (str): The magnification level, either 'square' or 'hole'.
        grid (AutoloaderGrid): The grid object.
    Returns:
        SimSiamWeights: The model weights if found, otherwise None.
    """
    weights = SimSiamWeights.objects.filter(mag_level=mag_level, grid_id=grid).first()
    if weights is not None:
        return
    sample_tags = grid.sample_tags.all()
    if len(sample_tags) > 0:
        weights = SimSiamWeights.objects.filter(mag_level=mag_level, sample_tag__in=sample_tags).all()
        if weights is not None:
            return weights
    project_tags = grid.project_tags.all()
    if len(project_tags) > 0:
        weights = SimSiamWeights.objects.filter(mag_level=mag_level, project_tag__in=project_tags).all()
        if weights is not None:
            return weights
    
def test():
    # Example usage
    grid_ids = ['1grid1D3E8saeD4rEAkt2dBEDTxC4T']  # Replace with actual grid IDs
    sim_siam_prepare_data('square', grid_ids)
    file_list = sim_siam_prepare_data('hole', grid_ids)
    sim_siam_copy_to_scratch_directory('sim_siam_hole', file_list)