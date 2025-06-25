from pathlib import Path
import json
from typing import Optional, Dict, List
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from Smartscope.core.models.tags import ProjectTag, SampleTag
from Smartscope.core.models import AutoloaderGrid


ROOT_WEIGHT_DIR = settings.AUTOSCREENDIR / 'weights' / 'sim_siam'

class SimSiamWeights(models.Model):
    """
    Model to store SimSiam model configurations.
    """
    name = models.CharField(max_length=255, help_text="Name of the SimSiam model.")
    mag_level = models.CharField(max_length=50, choices=[
        ('hole', 'Square'),
        ('square', 'Atlas')
    ], help_text="Magnification level of the model.")
    # weights_location = models.CharField(max_length=255, null=True, blank=True, help_text="Location where the model is saved.")
    # training_dataset_info = models.CharField(max_length=255, null=True, blank=True, help_text="Information about the dataset used for training the model.")
    project_tag = models.ForeignKey(ProjectTag, on_delete=models.SET_NULL, null=True, blank=True, help_text="Project tag associated with the model.")
    sample_tag = models.ForeignKey(SampleTag, on_delete=models.SET_NULL, null=True, blank=True, help_text="Sample tag associated with the model.")
    grid_id = models.ForeignKey(AutoloaderGrid, on_delete=models.CASCADE, related_name='sim_siam_models', null=True, blank=True, help_text="Grid ID associated with the model.")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Date and time when the model was created.")
    last_updated = models.DateTimeField(auto_now=True, help_text="Date and time when the model was last updated.")
    last_used = models.DateTimeField(null=True, blank=True, help_text="Date and time when the model was last used.")
    
    _dataset_info: Optional[Dict] = None

    def save(self, *args, **kwargs):
        """
        Override save method to ensure that the model name is unique within the training process.
        """
        if not self.is_dataset_info():
            raise ValueError("Dataset information must be set before saving the model.")
        super().save(*args, **kwargs)


    @property
    def weights_directory(self) -> Path:
        """
        Returns the location where the model weights are saved.
        """
        directory = ROOT_WEIGHT_DIR / f'{self.name}_{self.mag_level}'
        if not directory.is_dir():
            directory.mkdir(parents=True, exist_ok=True)
        return directory
    
    @property
    def checkpoint_file(self) -> Path:
        """
        Returns the path to the model checkpoint file.
        """
        return self.weights_directory / 'model_best.pth'
    
    @property
    def config_file(self) -> Path:
        """
        Returns the path to the model configuration file.
        """
        return self.weights_directory / f'simsiam_smartscope_{self.mag_level}s.yaml'

    @property
    def dataset_info_file(self):
        """
        Returns a string representation of the training dataset information.
        """
        return self.weights_directory / 'dataset_info.json'
    
    def set_dataset_info(self, dataset_info: dict):
        """
        Saves the dataset information to a JSON file.
        """
        self._training_dataset_info = dataset_info
        with open(self.dataset_info_file, 'w') as f:
            json.dump(dataset_info, f, indent=4)
        
    @property
    def dataset_info(self) -> Dict:
        """
        Loads the dataset information from a JSON file.
        """
        if self._training_dataset_info is None:
            if not self.is_dataset_info():
                raise FileNotFoundError("Dataset information file does not exist.")
            with open(self.dataset_info_file, 'r') as f:
                self._training_dataset_info = json.load(f)
        return self._training_dataset_info
        

    def is_dataset_info(self) -> bool:
        """
        Checks if the dataset information file exists.
        """
        return self.dataset_info_file.is_file()

    def __str__(self):
        return f"{self.name} - {self.mag_level}"

class SimSiamTrainingProcess(models.Model):
    """
    Model to store SimSiam training configurations and results.
    """
    dataset_name = models.CharField(max_length=255, help_text="Name of the dataset used for training.")
    training_date = models.DateTimeField(auto_now_add=True, help_text="Date and time when the training was performed.")
    process_id = models.CharField(max_length=255, null=True, blank=True, help_text="Unique identifier for the training process.")
    training_status = models.CharField(max_length=50, choices=[
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], default='pending', help_text="Current status of the training process.")
    sim_siam_weights = models.ForeignKey(SimSiamWeights, on_delete=models.CASCADE, related_name='training_processes', null=True, blank=True, help_text="Weights associated with the training process.")
    message = models.TextField(null=True, blank=True, help_text="Message or log related to the training process.")
    
    def __str__(self):
        return f'{self.training_date.strftime('%Y%m%d')}_{self.process_id}'
    
    @property
    def training_results_weights(self) -> Path:
        """
        Returns the directory where the training results are stored.
        """
        return Path(self.dataset_name, 'output', 'checkpoints', 'model_best.pth')
    
    @property
    def training_config_file(self) -> Path:
        """
        Returns the path to the training configuration file.
        """
        return Path(self.dataset_name, 'output', 'logs', f'simsiam_smartscope_{self.sim_siam_weights.mag_level}s.yaml')
    

