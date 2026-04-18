import json

from django.shortcuts import render
from django.views.generic.list import ListView
from django.http import JsonResponse
from django.db.models import Q, Prefetch, Avg, Max, Min

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework.renderers import TemplateHTMLRenderer

from .serializers import SessionSerializer
from Smartscope.core.models.screening_session import ScreeningSession
from Smartscope.core.models.grid import AutoloaderGrid
# from core.models import Product

def table_view(request):
    return render(request, "management_table.html")


class SessionsListView(APIView):
    # permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (ScreeningSession.objects
                    .select_related(
                        "group", "microscope_id", "user"
                    ).annotate(
                        grid_id=Min('autoloadergrid__grid_id'),
                        last_update=Max('autoloadergrid__last_update'),
                        avg_holes_per_square=Avg('autoloadergrid__params_id_id__holes_per_square'),
                    ).order_by("-creation_time")
                )

        filter_params = self.request.GET.get("filter", None)
        if filter_params:
            filters = json.loads(filter_params)
            q_objects = Q()

            for key, filter_info in filters.items():
                filter_type = filter_info.get("type")
                filter_value = filter_info.get("filter")

                if filter_type == "contains":
                    q_objects &= Q(**{f"{key}__icontains": filter_value})
                elif filter_type == "equals":
                    q_objects &= Q(**{f"{key}__exact": filter_value})
                elif filter_type == "notEqual":
                    q_objects &= ~Q(**{f"{key}__exact": filter_value})
                elif filter_type == "greaterThan":
                    q_objects &= Q(**{f"{key}__gt": filter_value})
                elif filter_type == "lessThan":
                    q_objects &= Q(**{f"{key}__lt": filter_value})

            queryset = queryset.filter(q_objects)

        sort_params = self.request.GET.get("sort", None)
        if sort_params:
            sort_fields = []
            for s in json.loads(sort_params):
                sort_fields.append(s["colId"] if s["sort"] == "asc" else f"-{s['colId']}")
            if sort_fields:
                queryset = queryset.order_by(*sort_fields)

        return queryset
    
    def get(self,request, *args, **kwargs):
        start_row = int(request.GET.get("startRow", 0))
        end_row = int(request.GET.get("endRow", 100))

        queryset = self.get_queryset()
        total_rows = queryset.count()
        page = queryset[start_row:end_row]

        serializer = SessionSerializer(page, many=True)
        return Response({"rows": serializer.data, "totalRows": total_rows})
    