import os
import json
import subprocess as sub
import psutil
from datetime import datetime
import logging
import plotly.graph_objs as go
import uuid


from django.shortcuts import render
from django.contrib.auth import logout, authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.template.response import TemplateResponse
from django.views.generic import TemplateView
from django.shortcuts import redirect
from django.utils.timezone import now

from Smartscope.tasks import long_actions_tasks

def start_job(request):
    job_id = str(uuid.uuid4())
    print(f"Starting long action job with id: {job_id}")
    # Trigger async job
    long_actions_tasks.test_long_running_task.delay(job_id)
    # Return the progress card HTML
    return render(request, "general/progress_card.html", {"job_id": job_id, "job_name": "Test Long Running Task"})

def regroup_bis_and_select_htmx(request, grid_id, square_id='all'):
    job_id = str(uuid.uuid4())
    print(f"Starting regroup BIS and select job with id: {job_id}")
    # Trigger async job
    long_actions_tasks.regroup_bis_and_select.delay(job_id, grid_id, square_id)
    # Return the progress card HTML
    return render(request, "general/progress_card.html", {"job_id": job_id, "job_name": "Regroup BIS and Select"})

def extend_lattice_global_htmx(request, grid_id):
    job_id = str(uuid.uuid4())
    print(f"Starting extend lattice global job with id: {job_id}")
    # Trigger async job
    long_actions_tasks.extend_lattice_global.delay(job_id, grid_id)
    # Return the progress card HTML
    return render(request, "general/progress_card.html", {"job_id": job_id, "job_name": "Extend Lattice Whole Grid"})