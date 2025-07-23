import cv2
import numpy as np
from Smartscope.bin import smartscope
from ..grid.finders import create_hole_ref_from_image
from ..grid.finders import find_targets
from ..models import AutoloaderGrid
from ..settings.worker import PLUGINS_FACTORY

from Smartscope.lib.image.montage import Montage

# def test_create_hole_ref_from_image():
#     montage = Montage('hole_ref', working_dir="")
#     montage.raw = '/mnt/testfiles/hole/Htr1_1_square35_hole469.mrc'
#     montage.load_or_process()
#     average = create_hole_ref_from_image(montage.image, montage.pixel_size/10, 1.2)
#     average = cv2.normalize(average, None, 0, 255, cv2.NORM_MINMAX)
#     initial = cv2.normalize(montage.image, None, 0, 255, cv2.NORM_MINMAX)
#     cv2.imwrite('hole_ref/intial.png', initial)
#     cv2.imwrite('hole_ref/average.png', average)

def test_mm_hole_finder_w_lattice():
    padding = 4000
    montage = Montage('mm_hole_finder_w_lattice', working_dir="")
    montage.raw = '/mnt/testfiles/hole/Htr1_1_square35_hole469.mrc'
    montage.load_or_process()
    grid = AutoloaderGrid.objects.get(pk="1Grid_1XJV0TuA2Cq639kznNi4FBky")
    targets, _,_,_ = find_targets(montage,["MM AI hole finder with lattice"], grid=grid)
    initial = cv2.normalize(montage.image, None, 0, 255, cv2.NORM_MINMAX)
    # initial = cv2.cvtColor(initial, cv2.COLOR_GRAY2BGR)
    image = cv2.copyMakeBorder(initial, *[padding]*4, cv2.BORDER_CONSTANT, value=0)
    for target in targets:
        cv2.circle(image, target.coords+np.array([padding]*2), 20, (255,0,0), -1)
    cv2.imwrite('mm_hole_finder_w_lattice/holes.png', image)