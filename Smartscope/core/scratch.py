import os
from typing import List
from pathlib import Path
from pydantic import BaseModel, field_validator
import shutil
import json
import time

from Smartscope.core.settings.worker import SCRATCH_DIR


class ScratchHistoryItem(BaseModel):
    """
    A class to represent a scratch history item.
    """
    timestamp: str
    name: str
    size_mb: float

class Scratch(BaseModel):
    """
    A class to represent a scratch object with a single attribute `scratch`.
    """
    scratch: Path = SCRATCH_DIR
    max_size_gb: int = 10

    @field_validator('scratch', mode='before')
    def _ensure_scratch(cls, v):
        """
        Ensure `scratch` is set. If `None`, default to `SCRATCH_DIR`.
        Also coerce strings to `Path`.
        """
        val = SCRATCH_DIR if v is None else v
        return val if isinstance(val, Path) else Path(val)

    @property
    def scratch_history(self) -> List:
        """
        Get the scratch directory path.
        Returns:
            str: The path to the scratch directory.
        """
        return self.scratch / "scratch_history.json"
    
    def read_scratch_history(self) -> List[ScratchHistoryItem]:
        """
        Read the scratch history from the JSON file.
        Returns:
            List[ScratchHistoryItem]: A list of ScratchHistoryItem objects.
        """
        if not self.scratch_history.exists():
            return []
        with open(self.scratch_history, 'r') as f:
            data = json.load(f)
        return [ScratchHistoryItem(**item) for item in data]
    
    def save_scratch_history(self, history: List[ScratchHistoryItem]):
        with open(self.scratch_history, 'w') as f:
            json.dump([item.model_dump() for item in history], f, indent=4)

    
    def write_scratch_history(self, item: ScratchHistoryItem):
        """
        Write a new item to the scratch history JSON file.
        Args:
            item (ScratchHistoryItem): The item to be added to the history.
        """
        history = self.read_scratch_history()
        #check if item name already exists, find its index and pop it out of the history
        for i, existing_item in enumerate(history):
            if existing_item.name == item.name:
                print(f"Item {item.name} already exists in scratch history, removing it.")
                history.pop(i)
                break
        history.append(item)
        self.save_scratch_history(history)


    @property
    def size(self) -> bool:
        """
        Check if the scratch directory size exceeds the maximum allowed size.
        Returns:
            bool: True if the size is within limits, False otherwise.
        """
        self.read_scratch_history()
        total_size = sum(item.size_mb for item in self.read_scratch_history())
        return total_size
    
    def check_size(self, file_list: List[Path], dataset_name: str):
        return sum(file.stat().st_size for file in file_list) / (1024**2)  # Convert bytes to MB
    
    def is_enough_space(self, space_required_mb) -> bool:
        """
        Check if there is enough space in the scratch directory.
        Args:
            space_required_mb (float): The required space in MB.
        Returns:
            bool: True if there is enough space, False otherwise.
        """
        total_size = self.size
        print(f"Total size in scratch: {total_size:.2f} MB, Required space: {space_required_mb:.2f} MB")
        return (total_size + space_required_mb) <= (self.max_size_gb * 1024)
    
    @property
    def available_space(self) -> float:
        """
        Get the available space in the scratch directory in MB.
        Returns:
            float: The available space in MB.
        """
        total_size = self.size
        return (self.max_size_gb * 1024) - total_size
    
    def make_space(self, space_required_mb: float):
        """
        Make space in the scratch directory by removing the oldest items until enough space is available.
        Args:
            space_required_mb (float): The required space in MB.
        """
        history = self.read_scratch_history()
        history.sort(key=lambda x: x.timestamp)
        space_to_free = space_required_mb - self.available_space
        while space_to_free > 0 and history:
            dataset = history.pop(0)
            dataset_path = self.scratch / dataset.name
            shutil.rmtree(dataset_path)
            space_to_free -= dataset.size_mb
            print(f"Removed {dataset.name} to free up space. Freed {dataset.size_mb:.2f} MB.")

        self.save_scratch_history(history)
            
    def copy_to_scratch(self, file_list:List[tuple[Path]], dataset_name:str) -> str:
        print(file_list)
        dataset_path = self.scratch / dataset_name
        total_size_mb = self.check_size([file[0] for file in file_list], dataset_name)
        if not self.is_enough_space(total_size_mb):
            self.make_space(total_size_mb)
        print(f'Scratch ready to copy {dataset_name} with size {total_size_mb:.2f} MB')
        dataset_path.mkdir(parents=True, exist_ok=True)
        for file, dest in file_list:
            if not file.exists():
                raise FileNotFoundError(f"File {file} does not exist.")
            destination:Path = dataset_path / dest
            if not destination.parent.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
            # print(f'Copying {file} to {dataset_path / dest}')
            shutil.copyfile(file, destination)

        item = ScratchHistoryItem(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            name=dataset_name,
            size_mb=total_size_mb
        )
        self.write_scratch_history(item)

    def copy_file_from_scratch(self, file: Path, output_directory: Path):
        """
        Copy a file from the scratch directory to the output directory.
        Args:
            file (Path): The file to be copied.
            output_directory (Path): The directory where the file will be copied.
        """
        file = self.scratch / file
        if not file.exists():
            raise FileNotFoundError(f"File {file} does not exist in scratch.")
        if not output_directory.exists():
            output_directory.mkdir(parents=True, exist_ok=True)
        shutil.copy(file, output_directory / file.name)

    def copy_directory_from_scratch(self, directory_name: str, output_directory: Path):
        """
        Copy a directory from the scratch directory to the output directory.
        Args:
            directory_name (str): The name of the directory to be copied.
            output_directory (Path): The directory where the files will be copied.
        """
        source_directory = self.scratch / directory_name
        if not source_directory.exists():
            raise FileNotFoundError(f"Directory {source_directory} does not exist in scratch.")
        if not output_directory.exists():
            output_directory.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_directory, output_directory, dirs_exist_ok=True)