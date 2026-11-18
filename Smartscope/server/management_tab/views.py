import io
import json
import logging
import tempfile
import zipfile
import shutil
from zoneinfo import ZoneInfo
from datetime import datetime
from pathlib import Path
import pandas as pd

from django.shortcuts import render
from django.db.models import Q, Prefetch, Avg, Max, Min, Count, Case, When, Value, CharField
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework import status

from .serializers import SessionSerializer
from Smartscope.core.models.screening_session import ScreeningSession
from Smartscope.core.models.grid import AutoloaderGrid
from Smartscope.core.settings import server_docker
from Smartscope.core.main_commands import export_session
from Smartscope.server.api.permissions import HasGroupPermission
# from core.models import Product


logger = logging.getLogger(__name__)


FILTER_FIELD_MAP = {
    "group": "group__name",
    "microscope": "microscope_id__name",
    "user": "user__username",
}


class EmptySessionError(Exception):
    """Session doesn't have valid grids exported."""
    pass


def _build_session_zip(session_id, tmp_dir):
    """
    Runs export_session into tmp_dir, then zips its contents into an
    in-memory buffer. Returns the buffer (positioned at 0).

    Raises:
        EmptySessionError: export_session completed but produced no files.
        Exception: export_session itself raised (re-raised with context).
    """
    try:
        export_session(session_id, export_to=tmp_dir)
    except Exception as err:
        raise Exception(
            f"export_session raised while exporting session {session_id} with error"
        ) from err

    tmp_path = Path(tmp_dir)
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    if not files:
        logger.warning(f"export_session produced no files for session {session_id}")
        raise EmptySessionError()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.relative_to(tmp_path))
    buffer.seek(0)
    return buffer


@login_required
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
    permission_classes = [IsAuthenticated]

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
                            When(avg_holes_per_square=-1, then=Value('collection')),
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


class SessionExportView(SessionsListView):
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = SessionSerializer(queryset, many=True)
        df = pd.DataFrame(serializer.data)
        columns_dict = {
            "session_label": "Session",
            "group": "Group",
            "microscope": "Microscope",
            "user": "User",
            "creation_time": "StartTime",
            "last_update": "EndTime",
            "session_type": "SessionType",
            "grid_count": "#Grids",
        }
        df = df[list(columns_dict.keys())].rename(columns=columns_dict)
        for cols in ["StartTime", "EndTime"]:
            df[cols] = df[cols].str.split('.').str[0]
            df[cols] = pd.to_datetime(df[cols], errors='coerce').dt.tz_localize(None)

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="sessions_history.xlsx"'
        df.to_excel(response, index=False, engine="openpyxl")
        return response


class SessionDetailExportView(APIView):
    """
    Exports a single session using the existing project export function.
    """
    permission_classes = [IsAuthenticated, HasGroupPermission]

    def get(self, request, session_id, *args, **kwargs):
        session = get_object_or_404(ScreeningSession, pk=session_id)
        self.check_object_permissions(request, session) 
        tmp_dir = tempfile.mkdtemp(prefix=f"session_{session.session_id}_export_")
        try:
            zip_name = f"session_{session.date}_{session.session}"
            zip_buffer = _build_session_zip(
                            session.session_id, 
                            tmp_dir)
            response = HttpResponse(zip_buffer.read(), content_type="application/zip")
            response["Content-Disposition"] = f'attachment; filename="{zip_name}.zip"'
            return response
        except EmptySessionError:
                    return Response(
                                {"detail": "No files were generated for this session."},
                                status=status.HTTP_404_NOT_FOUND,
                            )
        except Exception:
            logger.exception(f"export_session raised while exporting session {session_id}")
            return Response(
                        {"detail": "Export failed while generating session files."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class SessionDeleteView(APIView):
    """
    Deletes a single ScreeningSession: removes associated files on disk,
    then deletes the DB records. Restricted to the session's owner or staff.
    """
    permission_classes = [IsAuthenticated, HasGroupPermission]

    def delete(self, request, session_id, *args, **kwargs):
        session = get_object_or_404(ScreeningSession, pk=session_id)
        self.check_object_permissions(request, session)

        self._backup_session_before_delete(session)
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
        

    def _delete_session_files(self, session):
        session_dir = Path(session.directory)
        if session_dir.exists():
            shutil.rmtree(session_dir)
        else:
            logger.warning(f"Session directory not found, skipping file removal: {session_dir}")

    def _backup_session_before_delete(self, session):
        """
        Best-effort backup: writes a zip of the session's exported data into
        settings.SESSION_BACKUP_DIR before deletion. Failures are logged, not
        raised — deletion proceeds regardless, per policy.
        """
        backup_root = server_docker.SESSION_BACKUP_DIR
        tmp_dir = tempfile.mkdtemp(prefix=f"session_{session.session_id}_backup_")
        try:
            buffer = _build_session_zip(session.session_id, tmp_dir)
            backup_root.mkdir(parents=True, exist_ok=True)
            name = f"session_{session.date}_{session.session}.zip"
            backup_path = backup_root / name
            with open(backup_path, "wb") as f:
                f.write(buffer.read())
            logger.info(f"Backed up session {session.pk} to {backup_path}")
        except EmptySessionError:
            logger.warning(
                f"Session {session.pk} produced no files during pre-delete backup; "
                "proceeding with deletion without a backup archive."
            )
        except Exception:
            logger.exception(
                f"Failed to back up session {session.pk} before deletion; "
                "proceeding with deletion anyway per policy."
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)