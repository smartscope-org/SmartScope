import os
from Smartscope.core.settings.server_docker import REDIS_URL

accept_content = ['json']
result_accept_content = ['json']
result_backend = f"{REDIS_URL}/1"
broker_url = f"{REDIS_URL}/0"

QUEUES = os.getenv('QUEUES', 'celery').split(',')
TRANSIENT_QUEUES = os.getenv('TRANSIENT_QUEUES', [])
if isinstance(TRANSIENT_QUEUES, str):
    TRANSIENT_QUEUES = TRANSIENT_QUEUES.split(',')

TRANSIENT_QUEUES_CACHE_TIMEOUT = 300  # seconds

tasks_routes = {}

for queue in QUEUES:
    print(f"Registered queue: {queue}")
    tasks_routes['Smartscope.tasks.*'] = {'queue': 'celery'}




print(result_backend, broker_url)
# include = ['Smartscope.tasks.base_tasks']