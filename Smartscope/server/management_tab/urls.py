from django.urls import path
from django.views.generic import RedirectView

from .views import (
                    table_view, 
                    SessionsListView,
                    SessionExportView
                    )

urlpatterns = [
    path("", table_view, name='sessionHistory'),
    path("sessions/", SessionsListView.as_view(), name="sessions"),
    path("export-excel/", SessionExportView.as_view(), name="export_excel"),
]
