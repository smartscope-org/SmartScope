from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
import numpy as np
from django.db import transaction
from scipy.spatial.distance import cdist
from Smartscope.lib.Datatypes.base_plugin import Embedding, classLabel
from Smartscope.tasks.base_tasks import sim_siam_inference, sim_siam_training
from Smartscope.core.models import AtlasModel, SquareModel, AutoloaderGrid

from .models import SimSiamWeights, SimSiamTrainingProcess


class SimSiamEmbedding(Embedding):
    """
    Class for SimSiam embedding.
    """
    name: str = 'Sim Siam cluster'
    description: Optional[str] = "SimSiam embedding. This is a placeholder for the actual description."
    reference: Optional[str]= ''
    method: Optional[str] = 'send_sim_siam_data'
    module: Optional[str] = 'Smartscope.tasks.base_task'
    classes: Optional[Dict[(str, classLabel)]] = None
    draw_method: Optional[str] = None
    # create_targets_method:Literal['box','center']='box'
    kwargs: Optional[Dict[str, Any]] = dict(mag_level='square')
    grid_related_kwargs: Optional[Dict[str, Any]] = dict(grid_id='grid_id')
    colors: List = []
    # importPaths: Union[str,List] = Field(default_factory=list)


    def load_data(self, grid, mag_level, *args, **kwargs) -> pd.DataFrame:
        """Load data for the algorithm"""
        file = grid.directory / f'sim_siam_embeddings_{mag_level}.parquet.zip'
        print(f"Loading data from {file}")
        df = pd.read_parquet(file)
        print(df.head())
        # self.kwargs = kwargs
        # self.grid_related_kwargs = kwargs.get('grid_related_kwargs', {})
        # self.kwargs['mag_level'] = kwargs.get('mag_level', 'square')
        # self.grid_related_kwargs['grid_id'] = kwargs.get('grid_id', 'grid_id')
        return df
       
    def get_embedding_distances(self, data:pd.DataFrame, similar_to_ids) -> np.ndarray:
        embeddings =  np.array(data['embeddings'].tolist())
        print(embeddings.shape)
        print(similar_to_ids)
        print(data.index.isin(similar_to_ids))
        similar_to_embeddings = np.array(data[data.index.isin(similar_to_ids)]['embeddings'].tolist())
        print(similar_to_embeddings.shape)
        distances = cdist(embeddings, similar_to_embeddings, metric='euclidean')
        print(distances)
        min_distances = np.min(distances, axis=1)
        print(min_distances)
        return min_distances
    
    def suggest_similar(self,grid_id,mag_level, similar_to_ids: List[str], number_of_suggestions=3) -> List[str]:
        """
        Suggest similar squares or holes based on the grid ID and magnification level.
        Args:
        grid_id (str): The ID of the grid to be processed.
        mag_level (str): The magnification level, either 'square' or 'hole'.
        """
        grid = AutoloaderGrid.objects.get(grid_id=grid_id)
        data = self.load_data(grid, mag_level)
        # Validate the magnification level
        # if mag_level not in ['square', 'hole']:
        #     raise ValueError(f"Invalid magnification level: {mag_level}. Must be 'square' or 'hole'.")
        min_distances = self.get_embedding_distances(data, similar_to_ids)
        nearest_neighbors = np.argsort(min_distances)[number_of_suggestions:number_of_suggestions*2]
        print(nearest_neighbors)
        suggestions = data.iloc[nearest_neighbors].index.tolist()
        # Get the indices of the nearest neighbors

        # Send the data to the Celery task
        # ouput = send_sim_siam_suggest_similar(mag_level=mag_level, grid_id=grid_id)
        return suggestions
    
    def suggest_similar_from_distance(self, grid_id, mag_level, similar_to_ids: List[str], distance=2) -> List[str]:
        grid = AutoloaderGrid.objects.get(grid_id=grid_id)
        data = self.load_data(grid, mag_level)
        # Validate the magnification level
        # if mag_level not in ['square', 'hole']:
        #     raise ValueError(f"Invalid magnification level: {mag_level}. Must be 'square' or 'hole'.")
        min_distances = self.get_embedding_distances(data, similar_to_ids)
        distance = (np.max(min_distances) - np.min(min_distances)) * 0.1 + np.min(min_distances)
        
        nearest_neighbors = np.where((min_distances < distance) & (min_distances > 0))
        print(nearest_neighbors)
        print(f"Distance: {distance}")
        suggestions = data.iloc[nearest_neighbors].index.tolist()
        # Get the indices of the nearest neighbors

        # Send the data to the Celery task
        # ouput = send_sim_siam_suggest_similar(mag_level=mag_level, grid_id=grid_id)
        return suggestions

    # def get_embedding_clusters(self, grid_id, mag_level) -> List[int]:
    #     grid = AutoloaderGrid.objects.get(grid_id=grid_id)
    #     data = self.load_data(grid, mag_level)
    #     return data['assignments'].tolist()
    
    # def get_number_of_clusters(self, grid_id, mag_level) -> int:
    #     """
    #     Get the number of clusters for the given grid ID and magnification level.
    #     Args:
    #     grid_id (str): The ID of the grid to be processed.
    #     mag_level (str): The magnification level, either 'square' or 'hole'.
    #     """
    #     grid = AutoloaderGrid.objects.get(grid_id=grid_id)
    #     data = self.load_data(grid, mag_level)
    #     return len(set(data['assignments'].tolist()))
    
    def sorter_data(self, grid_id, mag_level, queryset) -> Tuple[List[str], List[int]]:
        """
        Get the data for the sorter.
        Args:
        grid_id (str): The ID of the grid to be processed.
        mag_level (str): The magnification level, either 'square' or 'hole'.
        """
        if isinstance(grid_id, str):
            grid = AutoloaderGrid.objects.get(grid_id=grid_id)
        else:
            grid = grid_id
        data = self.load_data(grid, mag_level)
        pks = queryset.values_list('pk', flat=True)
        data = data[data.index.isin(pks)]
        data = data.reindex(pks)
        clusters = data['assignments'].tolist()
        
        return clusters, len(set(clusters))


    def run(self, *args, **kwargs):
        """Where the main logic for the algorithm is"""

        output = sim_siam_inference(mag_level=kwargs['mag_level'], grid_id=kwargs['grid_id'])
        return output
    
    
    def run_training(self, *args, **kwargs):
        """
        Run the training process for the SimSiam model.
        This method is a placeholder and should be implemented with actual training logic.
        """
        grid = AutoloaderGrid.objects.get(grid_id=kwargs['grid_id'])
        mag_level = kwargs['mag_level']
        name = self.kwargs.get('name', f'SimSiam_{mag_level}_{grid.grid_id}')

        dataset_name = f"{grid.grid_id}_{mag_level}"

        weights = SimSiamWeights.objects.filter(name=name, mag_level=mag_level, grid_id=grid).first()
        found = True
        if weights is None:
            print(f'Creating new SimSiamWeights for {name} at magnification level {mag_level}')
            weights = SimSiamWeights(name=name, mag_level=mag_level)
            found = False

        weights.set_dataset_info([grid.grid_id])


        output = sim_siam_training(mag_level=mag_level, grid_id=grid.grid_id, dataset_name=dataset_name)


        if found:
            training_process = SimSiamTrainingProcess.objects.get(sim_siam_weights=weights)
            training_process.training_status = 'pending'
            training_process.dataset_name = dataset_name
            training_process.process_id = output
        else:
            training_process = SimSiamTrainingProcess(dataset_name=dataset_name, sim_siam_weights=weights, process_id=output, training_status='pending')

        with transaction.atomic():
            weights.save()
            training_process.save()


    def get_label(self, label):
        return self.colors[label]


        
