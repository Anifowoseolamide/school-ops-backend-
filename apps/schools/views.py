from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.permissions import RoleAccessMixin
from apps.core.roles import ADMIN, ALL_ROLES, BURSAR, MANAGEMENT, PRINCIPAL, TEACHER
from apps.core.utils import diff, snapshot
from apps.core.viewsets import SchoolModelViewSet

from .models import AcademicSession, ClassRoom, GradeBand, Subject, TeacherAssignment, Term
from .serializers import (
    AcademicSessionSerializer,
    ClassRoomSerializer,
    GradeBandSerializer,
    SchoolSerializer,
    SchoolSettingsSerializer,
    SubjectSerializer,
    TeacherAssignmentSerializer,
    TermSerializer,
)
from .services import get_settings, set_current_session, set_current_term, teacher_classroom_ids


class _AuditedSingletonView(RoleAccessMixin, generics.RetrieveUpdateAPIView):
    read_roles = ALL_ROLES
    write_roles = MANAGEMENT
    audit_action = ""

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = diff(before, snapshot(instance))
        if changes:
            record_audit(self.request, self.audit_action, instance, changes=changes)


@extend_schema_view(
    get=extend_schema(tags=["school"], summary="School profile"),
    put=extend_schema(tags=["school"], summary="Update school profile (principal, admin)"),
    patch=extend_schema(tags=["school"], summary="Update school profile (principal, admin)"),
)
class SchoolProfileView(_AuditedSingletonView):
    serializer_class = SchoolSerializer
    audit_action = "school.updated"

    def get_object(self):
        return self.request.user.school


@extend_schema_view(
    get=extend_schema(tags=["school"], summary="School settings (grading split, fees, report cards)"),
    put=extend_schema(tags=["school"], summary="Update school settings (principal, admin)"),
    patch=extend_schema(tags=["school"], summary="Update school settings (principal, admin)"),
)
class SchoolSettingsView(_AuditedSingletonView):
    serializer_class = SchoolSettingsSerializer
    audit_action = "school_settings.updated"

    def get_object(self):
        return get_settings(self.request.user.school)


@extend_schema_view(
    list=extend_schema(tags=["school"]),
    retrieve=extend_schema(tags=["school"]),
    create=extend_schema(tags=["school"]),
    update=extend_schema(tags=["school"]),
    partial_update=extend_schema(tags=["school"]),
    destroy=extend_schema(tags=["school"]),
)
class AcademicSessionViewSet(SchoolModelViewSet):
    queryset = AcademicSession.objects.all()
    serializer_class = AcademicSessionSerializer
    read_roles = ALL_ROLES
    write_roles = MANAGEMENT
    audit_label = "session"
    ordering_fields = ["start_date", "name"]

    @extend_schema(tags=["school"], summary="Make this the current session", request=None)
    @action(detail=True, methods=["post"], url_path="set-current")
    def set_current(self, request, pk=None):
        session = set_current_session(self.get_object())
        record_audit(request, "session.set_current", session)
        return Response(self.get_serializer(session).data)


@extend_schema_view(
    list=extend_schema(tags=["school"]),
    retrieve=extend_schema(tags=["school"]),
    create=extend_schema(tags=["school"]),
    update=extend_schema(tags=["school"]),
    partial_update=extend_schema(tags=["school"]),
    destroy=extend_schema(tags=["school"]),
)
class TermViewSet(SchoolModelViewSet):
    queryset = Term.objects.select_related("session")
    serializer_class = TermSerializer
    read_roles = ALL_ROLES
    write_roles = MANAGEMENT
    audit_label = "term"
    filterset_fields = ["session", "is_current", "name"]
    ordering_fields = ["start_date"]

    @extend_schema(tags=["school"], summary="Current term", responses=TermSerializer)
    @action(detail=False, methods=["get"])
    def current(self, request):
        term = self.get_queryset().filter(is_current=True).first()
        if term is None:
            return Response({"detail": "No current term is set.", "code": "no_current_term"}, status=404)
        return Response(self.get_serializer(term).data)

    @extend_schema(tags=["school"], summary="Make this the current term (also sets its session)", request=None)
    @action(detail=True, methods=["post"], url_path="set-current")
    def set_current(self, request, pk=None):
        term = set_current_term(self.get_object())
        record_audit(request, "term.set_current", term)
        return Response(self.get_serializer(term).data)


@extend_schema_view(
    list=extend_schema(tags=["school"], summary="Classes (teachers see only their own)"),
    retrieve=extend_schema(tags=["school"]),
    create=extend_schema(tags=["school"], summary="Create a class arm (admin)"),
    update=extend_schema(tags=["school"]),
    partial_update=extend_schema(tags=["school"]),
    destroy=extend_schema(tags=["school"]),
)
class ClassRoomViewSet(SchoolModelViewSet):
    """Bursars can read classes (needed for fee setup) but not teacher assignments."""

    queryset = ClassRoom.objects.select_related("class_teacher")
    serializer_class = ClassRoomSerializer
    read_roles = (PRINCIPAL, ADMIN, BURSAR, TEACHER)
    write_roles = (ADMIN,)
    action_roles = {"students": (PRINCIPAL, ADMIN, TEACHER)}
    audit_label = "classroom"
    filterset_fields = ["level", "class_teacher"]
    search_fields = ["arm"]
    ordering_fields = ["level_order", "arm"]

    def get_queryset(self):
        queryset = super().get_queryset().annotate(
            student_count=Count("students", filter=Q(students__status="active"), distinct=True)
        ).order_by("level_order", "arm")
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(id__in=teacher_classroom_ids(self.request.user))
        return queryset

    @extend_schema(tags=["school"], summary="Active students in this class")
    @action(detail=True, methods=["get"])
    def students(self, request, pk=None):
        from apps.students.serializers import StudentListSerializer

        classroom = self.get_object()
        queryset = classroom.students.filter(status="active").select_related("classroom").order_by(
            "last_name", "first_name"
        )
        page = self.paginate_queryset(queryset)
        serializer = StudentListSerializer(page if page is not None else queryset, many=True, context=self.get_serializer_context())
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(tags=["school"]),
    retrieve=extend_schema(tags=["school"]),
    create=extend_schema(tags=["school"]),
    update=extend_schema(tags=["school"]),
    partial_update=extend_schema(tags=["school"]),
    destroy=extend_schema(tags=["school"]),
)
class SubjectViewSet(SchoolModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    read_roles = ALL_ROLES
    write_roles = (ADMIN,)
    audit_label = "subject"
    search_fields = ["name", "code"]


@extend_schema_view(
    list=extend_schema(tags=["school"], summary="Teacher assignments (teachers see only their own)"),
    retrieve=extend_schema(tags=["school"]),
    create=extend_schema(tags=["school"], summary="Assign a teacher to a subject in a class (admin)"),
    update=extend_schema(tags=["school"]),
    partial_update=extend_schema(tags=["school"]),
    destroy=extend_schema(tags=["school"]),
)
class TeacherAssignmentViewSet(SchoolModelViewSet):
    queryset = TeacherAssignment.objects.select_related("session", "classroom", "subject", "teacher")
    serializer_class = TeacherAssignmentSerializer
    read_roles = (PRINCIPAL, ADMIN, TEACHER)
    write_roles = (ADMIN,)
    audit_label = "assignment"
    filterset_fields = ["session", "classroom", "subject", "teacher"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(teacher=self.request.user)
        return queryset


@extend_schema_view(
    list=extend_schema(tags=["school"], summary="Grading scale"),
    retrieve=extend_schema(tags=["school"]),
    create=extend_schema(tags=["school"]),
    update=extend_schema(tags=["school"]),
    partial_update=extend_schema(tags=["school"]),
    destroy=extend_schema(tags=["school"]),
)
class GradeBandViewSet(SchoolModelViewSet):
    queryset = GradeBand.objects.all()
    serializer_class = GradeBandSerializer
    read_roles = ALL_ROLES
    write_roles = MANAGEMENT
    audit_label = "grade_band"
    pagination_class = None
