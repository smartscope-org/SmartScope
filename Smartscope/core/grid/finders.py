import logging
from typing import Optional,Dict
import numpy as np
from operator import attrgetter
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.image.target import Target
from Smartscope.lib.Datatypes.base_plugin import TargetClass
from Smartscope.lib.image_manipulations import extract_from_image
from Smartscope.core.models import AutoloaderGrid
from Smartscope.core.settings.worker import PLUGINS_FACTORY, FORCE_MDOC_TARGETING

logger = logging.getLogger(__name__)

def parse_grid_related_kwargs(grid_related_kwargs:Dict, grid):
    """Parses the grid related kwargs and returns the values"""
    parsed = dict()
    for key, value in grid_related_kwargs.items():
        if isinstance(value, str):
            parsed[key] = attrgetter(value)(grid)
        else:
            raise TypeError(f'Value {value} is not a valid attribute of AutoloaderGrid. Expected str or dotted str')
    return parsed

def find_targets(montage: Montage, methods: list, grid:AutoloaderGrid=None ,**kwargs) -> tuple[Target, str, Optional[str], dict]:
    logger.debug(f'Using method: {methods}')
    
    for method in methods:
        method = PLUGINS_FACTORY.get_plugin(method)

        grid_related_kwargs = dict()
        if grid is not None:
            grid_related_kwargs = parse_grid_related_kwargs(method.grid_related_kwargs, grid)

        try:
            targets, success, additional_outputs  = method.run(montage=montage, class_map=method.classes, force_mdoc=FORCE_MDOC_TARGETING, **kwargs, **grid_related_kwargs)
        except Exception as err:
            logger.exception(err)
            success = False
            continue
        if success:
            logger.debug(f"{method} was successful: {success}, '+ \
                'Is Classifier: {method.target_class is TargetClass.CLASSIFIER}")
            if method.target_class is TargetClass.CLASSIFIER:
                return targets, method.name, method.name, additional_outputs
            else:
                return targets, method.name, None, additional_outputs
    return [], '', None, dict()

def create_hole_ref_from_image(image, pixel_size, hole_size):
    """Finds holes on a view mag image and then extracts and average them into a hole reference."""
    montage = Montage('hole_ref')
    montage.image = image
    targets, _, _, _ = find_targets(montage, ['Medium Mag AI hole finder'], convert_to_stage=False)
    print(f'Found {len(targets)} holes, pixel_size= {pixel_size}')
    stack = None
    for target in targets:

        crop, _, _, _, overLimits = extract_from_image(image,target.coords,pixel_size*10,box_size=hole_size*1.5)
        crop = crop.reshape((crop.shape + (1,)))
        print(f'Crop {crop.shape} is overlimits: {overLimits}. Stack created: {stack is not None}')
        if overLimits:
            continue
        if stack is None:
            stack = crop
            continue
        stack = np.concatenate((stack,crop),axis=2)
    average = np.mean(stack,axis=2).astype(image.dtype)
    return average