from typing import Callable, Optional, Dict
from Smartscope.lib.Finders.AIFinder.wrapper import find_holes_from_image, find_squares
from pydantic import BaseModel, Base64Bytes


class FindSquareKwargs(BaseModel):
    imgsz: int = 2048
    thresh: float = 0.2
    iou: float = 0.3
    weights: str = 'square_weights/model_large_atlas.pth'


class FindHolesKwargs(BaseModel):
    imgsz: int = 1280
    thresh: float = 0.2
    iou: float = 0.15
    weights_circle: str = 'circle_weights/circle_weight_12_7_21.pt'
    method: str = 'rcnn'
    success_threshold: float =  1
    class_mapping: dict = {}
    scaling_factor: float = 1


class FindSquaresRequest(BaseModel):
    image: Base64Bytes
    kwargs: FindSquareKwargs
    method: Callable= find_squares


class FindHolesRequest(BaseModel):
    image: Base64Bytes
    kwargs: FindHolesKwargs
    method: Callable= find_holes_from_image


METHODS_MAPPING = {
    'find_squares': FindSquaresRequest,
    'find_holes': FindHolesRequest,
}