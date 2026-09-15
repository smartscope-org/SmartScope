
import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import async_to_sync, sync_to_async

from Smartscope.core.autoscreen import update
from Smartscope.core.db_manipulations import viewer_only
from Smartscope.core.main_commands import session_full_state
from Smartscope.core.models.screening_session import ScreeningSession

logger = logging.getLogger(__name__)


class MetadataConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        grid_id = self.scope['url_route']['kwargs']['grid_id']
        logger.info(f'Socket is connected: {grid_id}')
        await self.channel_layer.group_add(
            grid_id,
            self.channel_name
        )
        self.groups.append(grid_id)
        await self.accept()

    async def receive(self, text_data):
        response = json.loads(text_data)
        user = self.scope["user"]

        logger.info(f'{self.groups[0]}, received: {response}, user: {user}, {type(user)}')
        # is_viewer_only = await sync_to_async(viewer_only)(user)
        # # This needs to be changed, implemented quickly for the demo server
        # if is_viewer_only:
        #     return await self.send(text_data='Cannot edit, user is part of the viewer_only group')
        return await self.channel_layer.group_send(self.groups[0], response)

    # async def update_target(self, event):
    #     response = await sync_to_async(update_target)(event['data'])
    #     # response.setdefault('type', 'update')
    #     await self.send(text_data=json.dumps(
    #         response))

    async def update_metadata(self, event):
        await self.send(text_data=json.dumps(
            {'type': 'update',
             'fullmeta': event['update'],
             }
        ))

    async def disconnect(self, event):
        logger.info(f'Socket {self.groups[0]} disconnected')
        await self.send(
            {"type": "websocket.close"}
        )


class ProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.job_id = self.scope["url_route"]["kwargs"]["job_id"]
        self.group_name = f"job_{self.job_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def progress_update(self, event):
        print(f"Progress update received: {event}")
        await self.send(text_data=json.dumps({
            "progress": event["progress"],
            "step": event["step"],
            "message": event["message"],
            "completed": event["completed"]
        }))

    async def progress_reload(self, event):
        # print(f"Progress reload received: {event}")
        await self.send(text_data=json.dumps({
            "type": "progress_reload",
            "reload": True
        }))


class SessionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.group_name = f"session_{self.session_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        current_state = await self.get_status(self.session_id)
        if current_state:
            for msg in current_state:
                await self.send(text_data=json.dumps(msg))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def session_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "session_status",
            "status": event["status"],
            "update_time": event["update_time"],
            "process_pid": event["process_pid"],
            "replay": event.get("replay", False)
        }))

    async def session_pause(self, event):
        await self.send(text_data=json.dumps({
            "type": "pause_status",
            "status": event["status"]
        }))

    async def session_pause_conf(self, event):
        await self.send(text_data=json.dumps({
            "type": "pause_conf",
            "status": event["status"]
        }))

    async def session_manage(self, event):
        await self.send(text_data=json.dumps({
            "type": "session_manage",
            "status": event["status"] # status is the new session's id that been set active
        }))

    async def session_logs(self, event):
        await self.send(text_data=json.dumps({
            "type": "session_logs",
            "line": event["line"],
            "process_type": event["process_type"]
        }))

    async def disk_status(self, event):
        await self.send(text_data=json.dumps({
            "type": "disk_status",
            "disk_usage": event["disk_usage"],
        }))

    @database_sync_to_async
    def get_status(self, session_id):
        try:
            return session_full_state(session_id)
        except ScreeningSession.DoesNotExist:
            return {}
    

    

