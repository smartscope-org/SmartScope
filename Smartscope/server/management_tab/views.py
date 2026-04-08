import json

from django.shortcuts import render
from django.views.generic.list import ListView
from django.http import JsonResponse
from django.db.models import Q

from core.models import Product

def table_view(request):
    return render(request, "management_table.html")


class ProductListView(ListView):
    model = Product

    def get_queryset(self):
        """
        Convert AgGrid filter and sort objects into a Django query.
        An example filter:
            {"category": {"type": "contains", "filter": "electronics"}}
        """
        queryset = super().get_queryset()

        filter_params = self.request.GET.get("filter", None)
        if filter_params:
            filters = json.loads(filter_params)
            q_objects = Q()

            for key, filter_info in filters.items():
                filter_type = filter_info.get("type")
                filter_value = filter_info.get("filter")

                if filter_type == "contains":
                    lookup = f"{key}__icontains"
                    q_objects &= Q(**{lookup: filter_value})
                elif filter_type == "equals":
                    lookup = f"{key}__exact"
                    q_objects &= Q(**{lookup: filter_value})
                elif filter_type == "notEqual":
                    lookup = f"{key}__exact"
                    q_objects &= ~Q(**{lookup: filter_value})
                elif filter_type == "greaterThan":
                    lookup = f"{key}__gt"
                    q_objects &= Q(**{lookup: filter_value})
                elif filter_type == "lessThan":
                    lookup = f"{key}__lt"
                    q_objects &= Q(**{lookup: filter_value})

            queryset = queryset.filter(q_objects)

        sort_params = self.request.GET.get("sort", None)
        if sort_params:
            sort_objects = json.loads(sort_params)
            sort_fields = []
            for sort_object in sort_objects:
                col_id = sort_object["colId"]
                sort_order = sort_object["sort"]
                if sort_order == "asc":
                    sort_fields.append(col_id)
                elif sort_order == "desc":
                    sort_fields.append(f"-{col_id}")

            if sort_fields:
                queryset = queryset.order_by(*sort_fields)
        return queryset

    def get(self, request, *args, **kwargs):
        start_row = int(request.GET.get("startRow", 0))
        end_row = int(request.GET.get("endRow", 100))

        queryset = self.get_queryset()

        total_rows = queryset.count()
        queryset = queryset[start_row:end_row]

        products = list(
            queryset.values(
                "name", "description", "category", "price", "stock_quantity", "rating"
            )
        )

        return JsonResponse({"rows": products, "totalRows": total_rows})