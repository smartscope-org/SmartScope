import os
from kombu import Queue

from Smartscope.core.settings.server_docker import REDIS_URL

accept_content = ['json']
result_accept_content = ['json']
result_backend = f"{REDIS_URL}/1"
broker_url = f"{REDIS_URL}/0"

QUEUES = os.getenv('QUEUES', 'smartscope_ai_cpu').split(',')
TRANSIENT_QUEUES = os.getenv('TRANSIENT_QUEUES', [])
TRANSIENT_SCRATCH = os.getenv('TRANSIENT_SCRATCH', [])
if isinstance(TRANSIENT_QUEUES, str):
    TRANSIENT_QUEUES = TRANSIENT_QUEUES.split(',')
    TRANSIENT_SCRATCH = TRANSIENT_SCRATCH.split(',')
    assert len(TRANSIENT_QUEUES) == len(TRANSIENT_SCRATCH), "TRANSIENT_QUEUES and TRANSIENT_SCRATCH must have the same length"

TRANSIENT_QUEUES_CACHE_TIMEOUT = 300  # seconds

task_queues = (
    Queue("celery"),
    Queue("smartscope"),
    Queue("smartscope_ai_rcnn"),
    Queue("smartscope_ai_cpu"),
)

task_routes = {
    "Smartscope.tasks.long_actions_tasks.*": {"queue": "smartscope"},
    "Smartscope.tasks.ai_tasks.*": {"queue": "smartscope_ai_rcnn"},
    "SmartscopeAI.interfaces.celery.tasks.*": {"queue": "smartscope_ai_cpu"},
}


task_default_queue = 'smartscope'


print(result_backend, broker_url)
# include = ['Smartscope.tasks.base_tasks']