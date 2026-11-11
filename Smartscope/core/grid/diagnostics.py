import numpy as np
import time
from pathlib import Path
from Smartscope.lib.image_manipulations import auto_contrast_sigma
import imutils
import cv2
import logging

logger = logging.getLogger(__name__)

def generate_diagnostic_figure(image:np.array, coords_set, outputpath:Path):
    image = auto_contrast_sigma(image)
    image_color = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    for coords, color, perc_im_radius in coords_set:
        radius = int(image_color.shape[0]*(perc_im_radius/100))
        for coord in coords:
            # logger.info(f'{coord}, {type(coord)}')
            cv2.circle(image_color,coord,radius,color=color, thickness=cv2.FILLED)
    cv2.imwrite(str(outputpath), imutils.resize(image_color,512))


def save_reregistration_diagnostics(directory, name:str, hole_img, square_img, result, hole_coords, det_hole, det_square):
    """Writes the medium-mag and square images plus the reregister_yolo match visualization
    for the YOLO-keypoint (v1) re-registration. Never raises."""
    from Smartscope.core.reregistration.reregister_yolo import visualize
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        hole_png = directory / f'{name}_reregister_medium.png'
        square_png = directory / f'{name}_reregister_square.png'
        cv2.imwrite(str(hole_png), hole_img)
        cv2.imwrite(str(square_png), square_img)
        visualize(str(hole_png), str(square_png), result, hole_coords,
                  str(directory / f'{name}_reregistration.png'),
                  detections_hole=det_hole, detections_square=det_square)
    except Exception as err:
        logger.warning(f'Could not save re-registration diagnostics for {name}: {err}')


class Timer:
    description_text:str

    def __init__(self, text:str):
        self.description_text = text

    def __enter__(self):
        logger.debug(f'Timer for {self.description_text} started')
        self.start = time.time()
        self.latest_timestamp = self.start
        return self

    def report_timer(self, text):
        current_time = time.time()
        timer = current_time - self.latest_timestamp
        total = current_time - self.start
        logger.debug(f'Step {text} took {timer:.2f} seconds. Total time elapsed: {total:.2f} seconds ')
        self.latest_timestamp = current_time

    def __exit__(self, exception_type, exception_value, traceback):
        timer = time.time() - self.start
        logger.debug(f'{self.description_text} took {timer:.2f} seconds to run.')
