import json
import logging
from zoneinfo import ZoneInfo
from datetime import datetime

from django.shortcuts import render
from django.db.models import Q, Prefetch, Avg, Max, Min, Count, Case, When, Value, CharField

from rest_framework.views import APIView
from rest_framework.response import Response

from .serializers import SessionSerializer
from Smartscope.core.models.screening_session import ScreeningSession
from Smartscope.core.models.grid import AutoloaderGrid
from Smartscope.core.settings import server_docker
# from core.models import Product


logger = logging.getLogger(__name__)


FILTER_FIELD_MAP = {
    "group": "group__name",
    "microscope": "microscope_id__name",
    "user": "user__username",
}

def table_view(request):
    return render(request, "management_table.html")

def utc_time_conversion(date: str,):
    try:
        naive_dt = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            # Fall back to date only, treat as local midnight
            naive_dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return None
    local_dt = naive_dt.replace(tzinfo=ZoneInfo(server_docker.TIME_ZONE))
    return local_dt.astimezone(ZoneInfo("UTC"))
        

class SessionsListView(APIView):
    # permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (ScreeningSession.objects
                    .select_related(
                        "group", "microscope_id", "user"
                    ).annotate(
                        grid_count=Count("autoloadergrid__grid_id"),
                        grid_id=Min("autoloadergrid__grid_id"),
                        last_update=Max("autoloadergrid__last_update"),
                        avg_holes_per_square=Avg("autoloadergrid__params_id_id__holes_per_square"),
                        grid_good=Count("autoloadergrid__quality", filter=Q(autoloadergrid__quality='good')),
                        grid_bad=Count("autoloadergrid__quality", filter=Q(autoloadergrid__quality='bad'))
                    ).annotate(
                        session_type=Case(
                            When(avg_holes_per_square=0, then=Value('collection')),
                            When(avg_holes_per_square__isnull=True, then=Value('unknown')),
                            default=Value('screening'),
                            output_field=CharField()
                        )
                    ).order_by("-creation_time")
                )

        filter_params = self.request.GET.get("filter", None)
        if filter_params:
            filters = json.loads(filter_params)
            q_objects = []

            for key, filter_info in filters.items():
                filter_type = filter_info.get("type")
                filter_value = filter_info.get("filter")
                print(f"key - {key}, filter - {filter_type}, value - {filter_value}")

                if filter_value is None:
                    continue

                if  key == "session_label": 
                    q_objects.append(Q(**{f"session__icontains": filter_value}) | Q(**{f"date__icontains": filter_value}))
                    continue
                if key in ["grid_count", "grid_bad", "grid_good"]:
                    filter_value = int(filter_value)
                if key in ["creation_time", "last_update"] and filter_value:
                    filter_value = utc_time_conversion(filter_value)

                db_field = FILTER_FIELD_MAP.get(key, key)
                if filter_type == "contains":
                    q_objects.append(Q(**{f"{db_field}__icontains": filter_value}))
                elif filter_type == "equals":
                    q_objects.append(Q(**{f"{db_field}__exact": filter_value}))
                elif filter_type == "greaterThan":
                    q_objects.append(Q(**{f"{db_field}__gt": filter_value}))
                elif filter_type == "lessThan":
                    q_objects.append(Q(**{f"{db_field}__lt": filter_value}))

            queryset = queryset.filter(*q_objects)

        sort_params = self.request.GET.get("sort", None)
        if sort_params:
            sort_fields = []
            for s in json.loads(sort_params):
                key = FILTER_FIELD_MAP.get(s["colId"], s["colId"])
                if key == "session_label":
                    sort_fields.append("date" if s["sort"] == "asc" else f"-date")
                    key = "session"
                sort_fields.append(key if s["sort"] == "asc" else f"-{key}")
            if sort_fields:
                queryset = queryset.order_by(*sort_fields)

        return queryset
    
    def get(self,request, *args, **kwargs):
        start_row = int(request.GET.get("startRow", 0))
        end_row = int(request.GET.get("endRow", 100))
        user = request.user
        logger.debug(f"{request.user}, {user.groups.values_list('id', flat=True)}")
        # print(user, user.groups)

        queryset = self.get_queryset()
        if user.is_staff:
            total_rows = queryset.count()
            page = queryset[start_row:end_row]
        else:
            subset = queryset.filter(group__in=user.groups.values_list("name", flat=True))
            total_rows = subset.count()
            page = subset[start_row:end_row]

        serializer = SessionSerializer(page, many=True)
        return Response({"rows": serializer.data, "totalRows": total_rows})
    