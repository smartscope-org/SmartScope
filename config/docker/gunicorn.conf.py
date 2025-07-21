import os
import logging
import logging.handlers
import sys

bind = "0.0.0.0:48001"
wsgi_app = 'Smartscope.server.main.asgi:application'
workers = 2
reload = False
capture_output = False

proc_name = 'smartscopeGunicorn'
# chdir = os.getenv('APP')
pidfile = '/tmp/smartscopeGunicorn_dev.pid'
worker_tmp_dir = '/tmp'
umask = int(os.getenv('DEFAULT_UMASK','002'))
# pythonpath = '/usr/local/bin/python'
worker_class = 'uvicorn.workers.UvicornWorker'
max_requests = 2000

log_dir = os.getenv('LOGDIR','../logs')

GUNICORN_LOG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'generic': {
            'format': '%(asctime)s [%(process)d] [%(levelname)s] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'generic',
            'stream': sys.stdout,

        },
        'error_file': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'formatter': 'generic',
            'filename': os.path.join(log_dir, 'gunicorn.log'),
            'when': 'midnight',
            'interval': 1,
            'backupCount': 90,
            'encoding': 'utf-8',
        },
        'access_file': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'formatter': 'generic',
            'filename': os.path.join(log_dir, 'gunicornAccess.log'),
            'when': 'midnight',
            'interval': 1,
            'backupCount': 90,
            'encoding': 'utf-8',
        },
    },
    'loggers': {
        '': {
            'level': os.getenv('LOGLEVEL'),
            'handlers': ['console', ],
        },
        'gunicorn.error': {
            'level': os.getenv('LOGLEVEL'),
            'handlers': ['error_file', ],
            'propagate': True,
        },
        'gunicorn.access': {
            'level': os.getenv('LOGLEVEL'),
            'handlers': ['access_file', ],
            'propagate': True
        },
    }
}


logconfig_dict = GUNICORN_LOG