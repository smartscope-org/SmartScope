from django.urls import path

from . import views

urlpatterns = [
    path('suggest_similar/', views.suggest_similar, name='sim_siam_suggest_similar'),
    path('training_callback/', views.sim_siam_training_callback_url, name='sim_siam_callback_url'),
]
