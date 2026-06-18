from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union
from packaging.version import Version


class Property(BaseModel):
    initial: Union[int, float, bool]
    readonly: bool = False
    disabled: bool = False
    advanced: bool = False
    hidden: bool = False

    @property
    def css_attr(self):
        remove_properties = ['initial', 'hidden', 'advanced']
        return {k:v for k, v in self.model_dump().items() if k not in remove_properties}
    

class DetectorParams(BaseModel):
    screening: Dict[str, Property] = Field(default_factory=dict)
    collection: Dict[str, Property] = Field(default_factory=dict)


class CustomDetectorParams(BaseModel):
    screening: Dict[str, Dict[str, Property]] = Field(default_factory=dict)
    collection: Dict[str, Dict[str, Property]] = Field(default_factory=dict)