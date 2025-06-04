from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union
from packaging.version import Version

class TargetPlugins(BaseModel):
    reregister: bool = True
    finders: List[str] = Field(default_factory=list)
    selectors: List[str] = Field(default_factory=list)

class MagLevel(BaseModel):
    acquisition: List[Union[str,Dict]]
    targets: Optional[TargetPlugins] = TargetPlugins()
    postActions: List[Union[str,Dict]] = Field(default_factory=list)

class PostActions(BaseModel):
    acquisition: List[Union[str,Dict]] = Field(default_factory=list)

class BaseProtocol(BaseModel):
    version: str = '0.1'
    name: str
    atlas: MagLevel
    square: MagLevel
    mediumMag: MagLevel
    highMag: MagLevel
    description: str = ''

    def is_version_supported(self, supported_version:str) -> bool:
        return Version(self.version) >= Version(supported_version)