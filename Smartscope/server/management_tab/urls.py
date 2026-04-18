from django.urls import path
from django.views.generic import RedirectView

from .views import (
                    table_view, 
                    SessionsListView
                    )

urlpatterns = [
    path("", table_view, name='sessionHistory'),
    path("sessions/", SessionsListView.as_view(), name="sessions"),
]
