from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import generics
from rest_framework.response import Response

from apps.core.permissions import RoleAccessMixin
from apps.core.roles import ADMIN, BURSAR, PRINCIPAL, TEACHER

from . import services


class _Dashboard(RoleAccessMixin, generics.GenericAPIView):
    pagination_class = None


class PrincipalDashboardView(_Dashboard):
    read_roles = (PRINCIPAL,)

    @extend_schema(
        tags=["dashboards"],
        summary="Principal: whole-school overview and 'needs attention' list",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        return Response(services.principal_dashboard(request.user.school))


class BursarDashboardView(_Dashboard):
    read_roles = (BURSAR, PRINCIPAL)

    @extend_schema(tags=["dashboards"], summary="Bursar: collections, outstanding and top debtors",
                   responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(services.bursar_dashboard(request.user.school))


class AdminDashboardView(_Dashboard):
    read_roles = (ADMIN, PRINCIPAL)

    @extend_schema(tags=["dashboards"], summary="Admin: setup gaps, results to review, recent changes",
                   responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(services.admin_dashboard(request.user.school))


class TeacherDashboardView(_Dashboard):
    read_roles = (TEACHER,)

    @extend_schema(tags=["dashboards"], summary="Teacher: my classes, attendance to mark, score sheets",
                   responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(services.teacher_dashboard(request.user))
