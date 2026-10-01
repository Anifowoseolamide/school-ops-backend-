import django_filters
from drf_spectacular.utils import extend_schema, extend_schema_view

from apps.core.roles import PRINCIPAL
from apps.core.viewsets import SchoolReadOnlyViewSet

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogFilter(django_filters.FilterSet):
    action = django_filters.CharFilter(field_name="action", lookup_expr="startswith")
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = AuditLog
        fields = ["actor", "actor_role", "action", "object_type", "object_id", "date_from", "date_to"]


@extend_schema_view(
    list=extend_schema(tags=["audit"], summary="Search the audit log (principal only)"),
    retrieve=extend_schema(tags=["audit"], summary="One audit log entry"),
)
class AuditLogViewSet(SchoolReadOnlyViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    read_roles = (PRINCIPAL,)
    filterset_class = AuditLogFilter
    search_fields = ["object_repr", "actor_email", "action"]
    ordering_fields = ["created_at", "action"]
