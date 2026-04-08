from django.urls import path
from django.views.generic import RedirectView

from .views import table_view, ProductListView


urlpatterns = [
    path("", table_view, name='sessionHistory'),
    path("sessions/", ProductListView.as_view(), name="sessions"),
]