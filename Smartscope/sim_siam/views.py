
import logging
import plotly.express as px

from django.http import HttpResponse, HttpRequest
from django.template.response import TemplateResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from Smartscope.core.models import AutoloaderGrid, HoleModel, SquareModel, AtlasModel
from Smartscope.core.selector_sorter import SelectorSorter, initialize_selector, save_selector_data, save_to_session_directory

from Smartscope.core.svg_plots import drawSelector
from Smartscope.core.status import status

from Smartscope.tasks.base_tasks import sim_siam_check_task

from .plugin import SimSiamEmbedding
from .models import SimSiamWeights, SimSiamTrainingProcess
from .prepare_data import sim_siam_transfer_trained_model


logger =logging.getLogger(__name__)


def parse_maglevel(maglevel='square'):
    if maglevel == 'square':
        return SquareModel
    elif maglevel == 'atlas':
        return AtlasModel


@api_view(['GET'])
def suggest_similar(request):
    logger.debug(f'Request received: {request.__dict__}')
    request_data = request.query_params
    grid_id = request_data.get('grid_id')
    similar_to_ids = request_data.get('similar_to_ids').split(',')
    number_of_suggestions = request_data.get('number_of_suggestions', 3)
    mag_level = request_data.get('mag_level', 'square')
    
    suggestions = SimSiamEmbedding().suggest_similar_from_distance(grid_id=grid_id, mag_level=mag_level, similar_to_ids=similar_to_ids)
    
    return Response({'suggestions':suggestions}, status=200, content_type='application/json')

@api_view(['POST'])
@authentication_classes([])
@permission_classes([])
def sim_siam_training_callback_url(request: HttpRequest):
    """
    Callback URL for SimSiam embedding.
    """
    logger.debug(f'Request received: {request.__dict__}')
    request_data = request.data
    process_id = request_data.get('process_id')
    
    process = SimSiamTrainingProcess.objects.filter(process_id=process_id).first()
    response = sim_siam_check_task(process_id)
    status = response.status
    if status == 'SUCCESS':
        # Update the process status to completed
        process.status = 'completed'
        process.message = response.info
        process.save()
        sim_siam_transfer_trained_model(process_id)
        return Response({'message': 'SimSiam training completed successfully.'}, status=200)
    if status == 'FAILURE':
        process.status = 'failed'
        process.message = response.info

    

