import logging
import logging.handlers
import os
import sys
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings

from Smartscope.utils.system_monitor import disk_space

logger = logging.getLogger(__name__)


def add_log_handlers(directory: str, name: str, session_id: str = None) -> None:
    main_handler = logging.FileHandler(os.path.join(directory, name), mode='a', encoding='utf-8')
    main_handler.setFormatter(logger.parent.handlers[0].formatter)
    logging.getLogger('Smartscope').addHandler(main_handler)
    if session_id:
        process_type = "_".join(name.split('.'))
        ws_handler = ChannelLogHandler(session_id, process_type)
        ws_handler.setLevel(logging.INFO)
        ws_handler.setFormatter(logger.parent.handlers[0].formatter)
        logging.getLogger('Smartscope').addHandler(ws_handler)


class ChannelLogHandler(logging.Handler):
    def __init__(self, session_id, name):
        super().__init__()
        self.session_id = session_id
        self.process_type = name
        self.channel_layer = get_channel_layer()

    def emit(self, record):
        try:
            line = self.format(record)
            async_to_sync(self.channel_layer.group_send)(
                f'session_{self.session_id}',
                {
                    'type': 'session.logs',
                    'process_type': self.process_type,
                    'line': line,
                }
            )
            async_to_sync(self.channel_layer.group_send)(
                f'session_{self.session_id}',
                {
                    'type': 'disk.status',
                    'disk_usage': disk_space(settings.AUTOSCREENDIR),
                }
            )
        except Exception:
            self.handleError(record)