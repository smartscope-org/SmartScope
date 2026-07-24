from channels.routing import URLRouter

# from django.conf.urls import url
from django.urls import path, re_path
from .consumers import MetadataConsumer, ProgressConsumer

router= URLRouter([
            path("websocket/grid_id=<grid_id>", MetadataConsumer.as_asgi()),
            re_path(r"websocket/progress/(?P<job_id>[^/]+)/$", ProgressConsumer.as_asgi())
            ])
