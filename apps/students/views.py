import csv

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.exceptions import Conflict
from apps.core.roles import ADMIN, BURSAR, PRINCIPAL, TEACHER
from apps.core.viewsets import SchoolModelViewSet, SchoolReadOnlyViewSet
from apps.schools.services import teacher_classroom_ids

from . import importer
from .models import Guardian, ImportStatus, Student, StudentImport
from .serializers import (
    GuardianSerializer,
    StudentBasicSerializer,
    StudentImportPreviewRequestSerializer,
    StudentImportSerializer,
    StudentListSerializer,
    StudentSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["students"],
        summary="List students",
        description="Principal and admin see all students; bursar sees basic details; "
        "teachers see only students in their own classes.",
    ),
    retrieve=extend_schema(tags=["students"], summary="Student details"),
    create=extend_schema(tags=["students"], summary="Create a student (admin)"),
    update=extend_schema(tags=["students"], summary="Edit a student (admin)"),
    partial_update=extend_schema(tags=["students"], summary="Edit a student (admin)"),
    destroy=extend_schema(
        tags=["students"],
        summary="Delete a student entered by mistake (admin)",
        description="Fails with 409 if the student already has invoices, scores or attendance. "
        "Set status to 'withdrawn' instead.",
    ),
)
class StudentViewSet(SchoolModelViewSet):
    queryset = Student.objects.select_related("classroom").prefetch_related("guardians")
    serializer_class = StudentSerializer
    read_roles = (PRINCIPAL, ADMIN, BURSAR, TEACHER)
    write_roles = (ADMIN,)
    action_roles = {"export": (PRINCIPAL, ADMIN)}
    audit_label = "student"
    filterset_fields = ["classroom", "status", "gender", "classroom__level"]
    search_fields = ["first_name", "last_name", "middle_name", "admission_number"]
    ordering_fields = ["last_name", "first_name", "admission_number", "created_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(classroom_id__in=teacher_classroom_ids(self.request.user))
        return queryset

    def get_serializer_class(self):
        if getattr(self, "swagger_fake_view", False):
            return StudentSerializer
        if self.request.user.role == BURSAR:
            return StudentBasicSerializer
        if self.action == "list":
            return StudentListSerializer
        return StudentSerializer

    @extend_schema(tags=["students"], summary="Download students as CSV (principal, admin)", responses={200: OpenApiTypes.BINARY})
    @action(detail=False, methods=["get"])
    def export(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="students.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Admission number",
                "Surname",
                "First name",
                "Middle name",
                "Gender",
                "Date of birth",
                "Class",
                "Status",
                "Guardian name",
                "Guardian phone",
                "Guardian email",
            ]
        )
        for s in queryset:
            g = min(s.guardians.all(), key=lambda guardian: guardian.id, default=None)
            writer.writerow(
                [
                    s.admission_number,
                    s.last_name,
                    s.first_name,
                    s.middle_name,
                    s.get_gender_display() if s.gender else "",
                    s.date_of_birth.strftime("%d/%m/%Y") if s.date_of_birth else "",
                    s.classroom.name if s.classroom_id else "",
                    s.get_status_display(),
                    g.full_name if g else "",
                    g.phone if g else "",
                    g.email if g else "",
                ]
            )
        record_audit(request, "student.exported", None, metadata={"count": queryset.count()})
        return response


@extend_schema_view(
    list=extend_schema(tags=["students"], summary="List guardians (teachers: only guardians of their students)"),
    retrieve=extend_schema(tags=["students"]),
    create=extend_schema(tags=["students"], summary="Create a guardian (admin)"),
    update=extend_schema(tags=["students"]),
    partial_update=extend_schema(tags=["students"]),
    destroy=extend_schema(tags=["students"]),
)
class GuardianViewSet(SchoolModelViewSet):
    queryset = Guardian.objects.prefetch_related("students__classroom")
    serializer_class = GuardianSerializer
    read_roles = (PRINCIPAL, ADMIN, BURSAR, TEACHER)
    write_roles = (ADMIN,)
    audit_label = "guardian"
    search_fields = ["first_name", "last_name", "phone", "email"]
    filterset_fields = ["students"]

    def _teacher_class_ids(self):
        if not hasattr(self, "_class_ids"):
            self._class_ids = teacher_classroom_ids(self.request.user)
        return self._class_ids

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(students__classroom_id__in=self._teacher_class_ids()).distinct()
        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False) and self.request.user.is_authenticated:
            if self.request.user.role == TEACHER:
                context["visible_student_ids"] = set(
                    Student.objects.filter(
                        school_id=self.request.user.school_id, classroom_id__in=self._teacher_class_ids()
                    ).values_list("id", flat=True)
                )
        return context


@extend_schema_view(
    list=extend_schema(tags=["students"], summary="Past imports (admin)"),
    retrieve=extend_schema(tags=["students"], summary="One import with its row errors (admin)"),
)
class StudentImportViewSet(SchoolReadOnlyViewSet):
    queryset = StudentImport.objects.select_related("uploaded_by")
    serializer_class = StudentImportSerializer
    read_roles = (ADMIN,)
    action_roles = {"preview": (ADMIN,), "commit": (ADMIN,)}
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        tags=["students"],
        summary="Upload a file and preview the import (nothing is saved yet)",
        request={"multipart/form-data": StudentImportPreviewRequestSerializer},
        responses={201: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["post"])
    def preview(self, request):
        serializer = StudentImportPreviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job, report = importer.preview_import(
                request.user.school,
                request.user,
                serializer.validated_data["file"],
                serializer.validated_data.get("column_mapping") or {},
            )
        except ValueError as exc:
            raise ValidationError({"file": str(exc)}) from exc
        record_audit(
            request,
            "student_import.previewed",
            job,
            metadata={"total_rows": job.total_rows, "valid_rows": job.valid_rows},
        )
        return Response(report, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["students"],
        summary="Create the valid rows of a previewed import",
        request=None,
        responses=StudentImportSerializer,
    )
    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        job = self.get_object()
        if job.status != ImportStatus.PREVIEWED:
            raise Conflict(f"This import is already {job.get_status_display().lower()}.")
        job = importer.commit_import(job)
        record_audit(
            request,
            "student_import.completed",
            job,
            metadata={"created": job.created_count, "skipped": len(job.error_rows)},
        )
        return Response(StudentImportSerializer(job, context=self.get_serializer_context()).data)
