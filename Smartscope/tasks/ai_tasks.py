import json
import requests
from celery.signals import task_postrun
from pydantic import BaseModel
import logging

from .app import app
from .objects import METHODS_MAPPING

logger = logging.getLogger(__name__)

@app.task
def ping():
    return True

@app.task
def find_squares(data: str):
    result = run_method('find_squares',data)
    print(result)
    return result

@app.task
def find_holes(data: str):
    result = run_method('find_holes',data)
    print(result)
    return result


def get_method(method:str) -> BaseModel:
    method = METHODS_MAPPING.get(method, None)
    if method is None:
        raise ValueError(f'Method {method} not found')
    return method

def run_method(method:str, data:dict):
    method: BaseModel = get_method(method)
    method = method.model_validate_json(data)
    logger.info(f'Run method with parameters {method.kwargs.dict()}')
    return method.method(image=method.image, **method.kwargs.dict())