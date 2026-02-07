from celery.result import AsyncResult
from Smartscope.tasks.app import app
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.image_manipulations import encode_image, to_8bits, convert_to_png, auto_contrast_sigma, fourier_crop
import json

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

def send_find_square():
    montage = Montage(name="grid_test_atlas",working_dir='/mnt/data/testing/20250113_test_creation/1_grid_test')
    montage.load_or_process()
    encoded = encode_image(montage.image)
    data = { 'image': encoded }
    data['kwargs'] = {}
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_squares', args=[json.dumps(data)], queue='celery')
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)

def send_find_hole():
    montage = Montage(name="atest4_square16",working_dir='/mnt/data/test/20260130_atest4/1_atest4')
    montage.load_or_process()
    image= convert_to_png(montage.image, height=1024, normalization=auto_contrast_sigma, binning_method=fourier_crop)
    encoded = encode_image(image)
    data = { 'image': encoded }
    data['kwargs'] = {
        'weights_circle' : 'circle_weights/20241122_view_mag_weight.pt',
        'method': 'yolo',
        'iou': 0.2,
        'scaling_factor': montage.image.shape[0] / 1024,
        'success_threshold': 1
        }
    data['kwargs']['class_mapping'] = {
        "0": {
                'value': -1,
                'name': 'Contamination',
                'color': 'LightGrey'
            },
        "1":{
                'value': 1,
                'name': 'Hole',
                'color': 'blue',
            },
        "2": {
                'value': -1,
                'name': 'Partial',
                'color': 'Silver',
            }
        }

    # find_holes_from_image(image, class_mapping, success_threshold, scaling_factor=scaling_factor, **kwargs)
    result = app.send_task('Smartscope.tasks.ai_tasks.find_holes', args=[json.dumps(data)], queue='celery')
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
# app.send_task('SmartscopeNotifications.celery.tasks.send_notification', args=[TEST_NOTIFICATION], queue='celery')

# send_find_square()
send_find_hole()
