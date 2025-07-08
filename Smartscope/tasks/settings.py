import os
from Smartscope.core.settings.server_docker import REDIS_URL

accept_content = ['json']
result_accept_content = ['json']
result_backend = f"{REDIS_URL}/1"
broker_url = f"{REDIS_URL}/0"

tasks_routes = {
    'smartscope.core.tasks.*': {'queue': 'smartscope'},
    'Smartscope.finders.tasks.*': {'queue': 'finders'},
    'Smartscope.tasks.*': {'queue': 'celery'},
}

print(result_backend, broker_url)
# include = ['Smartscope.tasks.base_tasks']