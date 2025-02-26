from celery.result import AsyncResult
from Smartscope.tasks.app import app
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.image_manipulations import encode_image, to_8bits
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
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_squares', args=[json.dumps(data)], queue='celery')
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)

def send_find_hole():
    montage = Montage(name="grid_1_square46",working_dir='/mnt/data/testing/20241206_test_new_protocols/1_grid_1')
    montage.load_or_process()
    encoded = encode_image(montage.image)
    data = { 'image': encoded }
    
    result = app.send_task('SmartscopeAI.interfaces.celery.tasks.find_holes', args=[json.dumps(data)], queue='celery')
    task_id = result.id
    res = AsyncResult(task_id, app=app)
    final_result = res.get(interval=1, timeout=120)
    print(final_result)
# app.send_task('SmartscopeNotifications.celery.tasks.send_notification', args=[TEST_NOTIFICATION], queue='celery')

# send_find_square()
send_find_hole()
