from celery import Celery
from . import settings

app = Celery()
app.config_from_object(settings)