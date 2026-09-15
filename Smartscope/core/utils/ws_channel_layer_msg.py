from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def broadcast_session_status(session_id: str, status: str, action: str, time: datetime | str = '', process_pid: int = None):
    channel_layer = get_channel_layer()
    logger.debug(f'Sending Session status change to websocket session_{session_id} group, new status - {status}')
    msg = {'type': f'session.{action}', 'status': status, 'process_pid': process_pid}
    msg['update_time'] = time.strftime("%Y-%m-%d %H:%M:%S") if time else time
    # msg['update_time'] = time.isoformat() if time else time
    async_to_sync(channel_layer.group_send)(
        f'session_{session_id}', msg
    )