import os

accept_content = ['json']
result_accept_content = ['json']
result_backend = f"redis://{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT')}/1"
broker_url = f"redis://{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT')}/0"

tasks_routes = {
    'smartscope.core.tasks.*': {'queue': 'smartscope'},
    'Smartscope.finders.tasks.*': {'queue': 'finders'},
    'Smartscope.tasks.*': {'queue': 'celery'},
}

print(result_backend, broker_url)
# include = ['Smartscope.tasks.base_tasks']