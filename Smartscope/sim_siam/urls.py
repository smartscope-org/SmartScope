from django.urls import path

from . import views

urlpatterns = [
    path('suggest_similar/', views.suggest_similar, name='sim_siam_suggest_similar'),
]
