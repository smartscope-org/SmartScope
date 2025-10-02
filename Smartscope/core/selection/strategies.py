
from typing import Literal, List, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod
import pandas as pd
import random
import logging
from Smartscope.core.data_manipulations import select_n_areas, filter_targets, prune_targets
from Smartscope.core.models import Target, SquareModel, HoleModel, AutoloaderGrid
from Smartscope.core.navigation import TargetPriority

logger = logging.getLogger(__name__)

@dataclass
class TargetSelectionStrategy(ABC):
    n_targets: int = 3
    mode: str = 'screening'
    name: str = 'target_selection_strategy'
    ordered_priority_in_selection: bool = False
    target_priority: Optional[TargetPriority] = None

    @abstractmethod
    def select(self, item:Target, **kwargs):
        """Select target areas from the data."""
        pass

    def __post_init__(self):
        if self.mode not in ['screening', 'classification']:
            raise ValueError(f"Invalid mode: {self.mode}. Choose 'screening' or 'classification'.")


@dataclass
class OriginalTargetSelectionStrategy(TargetSelectionStrategy):
    name: str = 'Original'

    def select_squares(self, item:Target):
        selection = select_n_areas(item, self.n_targets)
        return selection, [1] * len(selection)
    
    def select_holes(self, item:Target, is_bis=False):
        selection = select_n_areas(item, self.n_targets, is_bis=is_bis)
        return selection, [1] * len(selection)          

    def select(self, item:Target, is_bis=False, **kwargs):
        if item.prefix_lower == 'atlas':
            return self.select_squares(item)
        if item.prefix_lower == 'square':
            return self.select_holes(item, is_bis=is_bis)




@dataclass
class ThoroughTargetSelectionStrategy(TargetSelectionStrategy):
    coverage_threshold: float = 0.8
    target_priority: TargetPriority = TargetPriority.SQUARE
    name: str = 'Thorough'
    ordered_priority_in_selection: bool = True

    def get_queryset(self, mag_level:Literal['atlas', 'square'], grid:AutoloaderGrid):
        """Get the queryset of targets to select from."""
        if mag_level == 'atlas':
            return list(SquareModel.display.filter(grid_id=grid))
        if mag_level == 'square':
            return list(HoleModel.display.filter(grid_id=grid))
        raise ValueError(f"Unsupported target type: {mag_level}")
    
    def create_selection_data(self, items, filtered, include_bis_group=False) -> pd.DataFrame:
        """
        Create a DataFrame with the selection data for holes or squares.

        Args:
            items: List of hole or square objects.
            filtered: List of corresponding filters.
            include_bis_group: Whether to include the 'bis_group' column (used for holes).

        Returns:
            A pandas DataFrame indexed by 'pk'.
        """
        rows = []
        for item, f in zip(items, filtered):
            row = {
                'pk': item.pk,
                # 'stage_coords': item.stage_coords,
                'filters': f,
                'selected': item.status not in [None,'queued'],
            }
            if include_bis_group:
                row['bis_group'] = item.bis_group if item.bis_group is not None else item.pk
            rows.append(row)

        return pd.DataFrame(rows).set_index('pk')

    def extract_features(self, grid:AutoloaderGrid, queryset):
        filtered = filter_targets(grid, queryset)
        return filtered
    

    def filter_by_selection(self, data: pd.DataFrame) -> tuple[pd.DataFrame, set]:
        all_assignments = set(data['filters'].to_list())
        selected = data[data['selected']]
        already_selected_assignments = set(selected['filters'].to_list())
        remaining_assignments = all_assignments - already_selected_assignments
        unselected_data = data[~data['selected']]
        logger.info(f"{len(remaining_assignments)} of {len(all_assignments)} unique assignments are not selected yet.")
        return unselected_data, all_assignments, remaining_assignments
    
    def prepare_data(self, grid:AutoloaderGrid, maglevel:Literal['atlas', 'square']) -> pd.DataFrame:
        """Prepare the data for selection."""
        queryset = self.get_queryset(maglevel, grid)
        filtered = self.extract_features(grid, queryset)
        data = self.create_selection_data(queryset, filtered, include_bis_group=(maglevel == 'square'))
        data = data[~data['filters'].str.contains('0', na=False)]
        return queryset, data
    
    def get_sampling_subset(self, data: pd.DataFrame) -> pd.DataFrame:
        unselected_data, all_assignments, remaining_assignments = self.filter_by_selection(data)

        grouped = data.groupby('filters').apply(lambda g: g.index.tolist()).reset_index(name='pks')
        grouped['num_pks'] = grouped['pks'].apply(len)
        #Remove the selected pks from the grouped data
        grouped['pks'] = grouped['pks'].apply(lambda x: list(set(x).intersection(set(unselected_data.index.to_list()))))
        grouped = grouped.sort_values(by='num_pks', ascending=False).reset_index(drop=True)
        cumsum = grouped['num_pks'].cumsum()
        threshold = grouped['num_pks'].sum() * self.coverage_threshold

        # Get the index of the last row where cumsum < threshold
        below_threshold = cumsum < threshold
        last_index = len(below_threshold[below_threshold])
        

        # Get the row after that (by position)
        # last_pos = grouped.index.get_loc(last_index)
        grouped =  grouped.iloc[:last_index + 1]
        logger.info(f'{self.coverage_threshold * 100}% of all items are represented in {len(grouped)}/{len(all_assignments)} unique types of items.')
        #only keep the groups that are in the remaining assignments
        grouped = grouped[grouped['filters'].isin(remaining_assignments)]
        logger.info(f'After checking against the already-collected areas, {len(grouped)} groups of items are left to sample from.')
        # logger.debug(f'Grouped data:\n{grouped.head()}')
        return grouped

    def select_squares(self, grid:AutoloaderGrid) -> List[Target]:
        """Select squares from the grid."""
        queryset, data = self.prepare_data(grid, 'atlas')
        grouped = self.get_sampling_subset(data)
        grouped['selection'] = grouped['pks'].apply(random.choice)
        selected = list(filter(lambda x: x.pk in grouped['selection'].to_list(), queryset))
        return selected, grouped.index.to_list()

    def select_holes(self, grid:AutoloaderGrid) -> List[Target]:

        def assignments_left(assignment):
            new_set =  assignment - first_group['filters']
            return new_set
        
        queryset, data = self.prepare_data(grid, 'square')
        grouped = self.get_sampling_subset(data)
        
        set_of_filters_to_sample = set(grouped.filters.to_list())
        if len(set_of_filters_to_sample) == 0:
            logger.info("No filters left to sample from. Returning empty selection.")
            return []

        grouped_bis= data.groupby('bis_group').agg(
            filters= ('filters',lambda x: set_of_filters_to_sample.intersection(set(x))),
            group_size= ('filters','size'))
        grouped_bis['num_assignments'] = grouped_bis['filters'].apply(len)
        grouped_bis = grouped_bis.sort_values(by=['num_assignments'], ascending=[False])

        selection = []
        while True:
            starting_assignments = len(set_of_filters_to_sample)
            first_group = grouped_bis.iloc[0]
            grouped_bis = grouped_bis.drop(first_group.name)
            set_of_filters_to_sample= set_of_filters_to_sample - first_group['filters']
            logger.info(f"Missing assignments in first group: {len(set_of_filters_to_sample)}")
            #remove all groups that have the same assignments as the first group
            grouped_bis['filters'] = grouped_bis['filters'].apply(assignments_left)
            grouped_bis = grouped_bis.sort_values(by=['num_assignments'], ascending=[False])
            grouped_bis= grouped_bis.sort_values(by=['filters'], key=lambda x: x.apply(len), ascending=[False])
            selection.append(first_group)
            if len(set_of_filters_to_sample) == 0:
                break 
            if starting_assignments == len(set_of_filters_to_sample):
                logger.info("No more assignments left to select from. Stopping.")
                break

        selection = pd.DataFrame(selection)

        logger.info(f'All {len(grouped)} types of holes can be collected from {selection.shape[0]} groups of holes, totalling {selection["group_size"].sum()} images.')
        selected = list(filter(lambda x: all([x.bis_group in selection.index.to_list(), x.bis_type == 'center']) or x.pk in selection.index.to_list(), queryset))
        print(selection.index.to_list(), selected)
        return selected, grouped.index.to_list()

    def select(self, item:Target, **kwargs):
        if item.prefix_lower == 'atlas':
            return self.select_squares(item.grid_id)
        if item.prefix_lower == 'square':
            return self.select_holes(item.grid_id)

@dataclass       
class RepresentativeTargetSelectionStrategy(ThoroughTargetSelectionStrategy):
    coverage_threshold: float = 0.5
    name: str = 'Representative'

@dataclass
class NoLabelsCollectionTargetSelectionStrategy(TargetSelectionStrategy):
    """
    Base class for data collection strategies.
    """
    coverage_threshold: float = 0.8
    target_priority: TargetPriority = TargetPriority.SQUARE
    name: str = 'No Labels Collection'
    ordered_priority_in_selection: bool = True




    def select(self, item:Target, **kwargs):
        pass



TARGET_SELECTION_STRATEGIES = {
    'original': OriginalTargetSelectionStrategy,
    'thorough': ThoroughTargetSelectionStrategy,
    'representative': RepresentativeTargetSelectionStrategy,
}
