from celery.result import AsyncResult
from celery.exceptions import TimeoutError
import json
from typing import Dict
import logging
from pydantic import BaseModel

from Smartscope.tasks.app import app
from Smartscope.tasks.base_tasks import get_queue
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.image_manipulations import encode_image
from Smartscope.lib.image_manipulations import convert_to_png, auto_contrast_sigma, fourier_crop
from Smartscope.lib.Finders.basic_finders import mask_square


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


def send_find_squares(montage, class_map:Dict[str,BaseModel], **kwargs):

    encoded = encode_image(montage.image)
    data = {'image': encoded}
    data['kwargs'] = kwargs
    
    result = app.send_task('Smartscope.tasks.ai_tasks.find_squares', args=[json.dumps(data)])
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    squares, labels = res.get(interval=1, timeout=120)
    success = True
    if len(squares) < 20 and montage.image.shape[0] > 20000:
        success = False
    print(squares, labels)
    return (squares,labels), success, dict()


def send_find_holes(montage:Montage, class_map:Dict[str,BaseModel], success_threshold:int=10,  **kwargs):
    scaling_factor = montage.image.shape[0] / kwargs.get('imgsz', 1024)
    image= convert_to_png(montage.image, height=kwargs.get('imgsz', 1024), normalization=auto_contrast_sigma, binning_method=fourier_crop)

    encoded = encode_image(image)

    data = {'image': encoded}
    data['kwargs'] = kwargs
    data['kwargs']['scaling_factor'] = scaling_factor
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('Smartscope.tasks.ai_tasks.find_holes', args=[json.dumps(data)])
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
    return final_result, True, dict()

def send_find_holes_from_square(montage:Montage, class_map:Dict[str,BaseModel], success_threshold:int=10,  **kwargs):
    scaling_factor = montage.image.shape[0] / kwargs.get('imgsz', 1024)
    image= convert_to_png(montage.image, height=kwargs.get('imgsz', 1024))
    image = mask_square(image)

    encoded = encode_image(image)

    data = { 'image': encoded }
    data['kwargs'] = kwargs
    data['kwargs']['scaling_factor'] = scaling_factor
    data['kwargs']['class_mapping'] = {k:v.model_dump() for k,v in class_map.items()}
    
    result = app.send_task('Smartscope.tasks.ai_tasks.find_holes', args=[json.dumps(data)])
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
    return final_result, True, dict()
