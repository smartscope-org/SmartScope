from django.urls import path
from django.views.generic import RedirectView

from .views import (
                    table_view, 
                    SessionsListView,
                    SessionExportView,
                    SessionDetailExportView,
                    SessionDeleteView
                    )

urlpatterns = [
    path("", table_view, name='sessionHistory'),
    path("sessions/", SessionsListView.as_view(), name="sessions"),
    path("export-excel/", SessionExportView.as_view(), name="export_excel"),
    path("sessions/<str:session_id>/export/", SessionDetailExportView.as_view(), name="session_detail_export"),
    path("sessions/<str:session_id>/delete/", SessionDeleteView.as_view(), name="session_delete"),
]
