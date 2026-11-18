import logging

from Smartscope.core.cache import save_json_from_cache
from Smartscope.core.models import GridCollectionParams, AutoloaderGrid
from Smartscope.server.api.serializers import GridCollectionParamsSerializer, AutoloaderGridSerializer

logger =logging.getLogger(__name__)

def update_collection_params(grid, data):
    try:
        data = data.copy()
        multishot_per_hole_id = data.pop('multishot_per_hole_id', None)
        if multishot_per_hole_id:
            save_json_from_cache(multishot_per_hole_id, grid.directory, 'multishot')
        serializer = GridCollectionParamsSerializer(data=data, partial=True)
        if serializer.is_valid():
            params, created = GridCollectionParams.objects.get_or_create(**serializer.validated_data)
            grid.params_id = params
            grid.save()
            return {'success': True}
        return {'success': False, 'errors': serializer.errors}
    except Exception as err:
        logger.exception(f'Error while updating parameters: {err}')
        return {'success': False, 'errors': err}
    

def update_grid(grid, data):
    serializer = AutoloaderGridSerializer(instance=grid, data=data, partial=True)
    logger.info(f"Grid serializer output: {serializer.is_valid()}")
    if serializer.is_valid():
        serializer.save()
        return {'success': True}
    else:
        logger.debug(f'Serializer errors: {serializer.errors}')
        return {'success': False, 'errors': serializer.errors}