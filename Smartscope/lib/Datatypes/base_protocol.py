from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union
from packaging.version import Version

class TargetPlugins(BaseModel):
    reregister: bool = True
    finders: List[str] = Field(default_factory=list)
    selectors: List[str] = Field(default_factory=list)
    fiducial_finders: List[str] = Field(default_factory=list)

class ScopeActions(BaseModel):
    steps: List[Union[str,Dict]] = Field(default_factory=list)

class MagLevel(ScopeActions):
    targets: Optional[TargetPlugins] = TargetPlugins()
    postActions: List[Union[str,Dict]] = Field(default_factory=list)

class BaseProtocol(BaseModel):
    version: str = '0.2'
    name: str
    preImaging: ScopeActions
    atlas: MagLevel
    square: MagLevel
    mediumMag: MagLevel
    highMag: MagLevel
    postHighMag: ScopeActions
    description: str = ''

    def is_version_supported(self, supported_version:str) -> bool:
        return Version(self.version) >= Version(supported_version)