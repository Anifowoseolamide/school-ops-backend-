import django_filters
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.permissions import RoleAccessMixin
from apps.core.roles import ADMIN, PRINCIPAL, TEACHER
from apps.core.viewsets import SchoolReadOnlyViewSet
from apps.schools.services import resolve_term, teacher_classroom_ids, term_for_date
from apps.students.models import Student

from .models import AttendanceRecord
from .serializers import (
    AttendanceRecordSerializer,
    RegisterQuerySerializer,
    RegisterResponseSerializer,
    RegisterSaveSerializer,
)
from .services import class_register, save_register, student_attendance_summary, summary_for_day, today


def _register_payload(classroom, day):
    students, records = class_register(classroom, day)
    term = term_for_date(classroom.school, day)
    latest = max(records.values(), key=lambda r: r.updated_at, default=None)
    return {
        "classroom": {"id": classroom.id, "name": classroom.name},
        "date": day,
        "term": {"id": term.id, "name": str(term)} if term else None,
        "is_marked": bool(records),
        "marked_by": latest.marked_by.full_name if latest and latest.marked_by_id else None,
        "marked_at": latest.updated_at if latest else None,
        "students": [
            {
                "student": s.id,
                "full_name": s.full_name,
                "admission_number": s.admission_number,
                "status": records[s.id].status if s.id in records else "present",
                "note": records[s.id].note if s.id in records else "",
                "is_marked": s.id in records,
            }
            for s in students
        ],
    }


class RegisterView(RoleAccessMixin, generics.GenericAPIView):
    """A class's attendance register for one day.

    GET shows the register (unmarked students default to present).
    POST saves it. Teachers can only mark classes they are form teacher of or teach.
    """

    read_roles = (PRINCIPAL, ADMIN, TEACHER)
    write_roles = (TEACHER,)
    serializer_class = RegisterSaveSerializer

    def _classroom_for(self, serializer):
        classroom = serializer.validated_data["classroom"]
        if self.request.user.role == TEACHER and classroom.id not in teacher_classroom_ids(self.request.user):
            raise NotFound("Class not found.")
        return classroom

    @extend_schema(
        tags=["attendance"],
        summary="Get a class register for a day",
        parameters=[
            OpenApiParameter("classroom", OpenApiTypes.INT, required=True),
            OpenApiParameter("date", OpenApiTypes.DATE, description="Defaults to today"),
        ],
        responses=RegisterResponseSerializer,
    )
    def get(self, request):
        serializer = RegisterQuerySerializer(data=request.query_params, context={"request": request})
        serializer.is_valid(raise_exception=True)
        classroom = self._classroom_for(serializer)
        day = serializer.validated_data.get("date") or today()
        return Response(RegisterResponseSerializer(_register_payload(classroom, day)).data)

    @extend_schema(
        tags=["attendance"],
        summary="Save a class register (teacher)",
        request=RegisterSaveSerializer,
        responses=RegisterResponseSerializer,
    )
    def post(self, request):
        serializer = RegisterSaveSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        classroom = self._classroom_for(serializer)
        day = serializer.validated_data.get("date") or today()
        if term_for_date(classroom.school, day) is None:
            raise ValidationError({"date": "This date is not inside any term. Check the term dates."})
        class_student_ids = set(
            Student.objects.filter(classroom=classroom, status="active").values_list("id", flat=True)
        )
        entries = {}
        for entry in serializer.validated_data.get("records", []):
            if entry["student"] not in class_student_ids:
                raise ValidationError({"records": f"Student {entry['student']} is not an active student of this class."})
            entries[entry["student"]] = (entry["status"], entry.get("note", ""))
        term, saved = save_register(classroom, day, entries, request.user)
        record_audit(
            request,
            "attendance.marked",
            classroom,
            metadata={
                "date": day.isoformat(),
                "students": len(saved),
                "absent": sum(1 for r in saved if r.status == "absent"),
                "late": sum(1 for r in saved if r.status == "late"),
            },
        )
        return Response(RegisterResponseSerializer(_register_payload(classroom, day)).data)


class AttendanceFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = AttendanceRecord
        fields = ["student", "classroom", "term", "date", "status", "date_from", "date_to"]


@extend_schema_view(
    list=extend_schema(tags=["attendance"], summary="Search attendance records"),
    retrieve=extend_schema(tags=["attendance"]),
)
class AttendanceRecordViewSet(SchoolReadOnlyViewSet):
    queryset = AttendanceRecord.objects.select_related("student", "classroom", "marked_by")
    serializer_class = AttendanceRecordSerializer
    read_roles = (PRINCIPAL, ADMIN, TEACHER)
    filterset_class = AttendanceFilter
    ordering_fields = ["date", "student__last_name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(classroom_id__in=teacher_classroom_ids(self.request.user))
        return queryset


class DailySummaryView(RoleAccessMixin, generics.GenericAPIView):
    read_roles = (PRINCIPAL, ADMIN, TEACHER)

    @extend_schema(
        tags=["attendance"],
        summary="Attendance per class for a day (which classes are marked, who is absent)",
        parameters=[OpenApiParameter("date", OpenApiTypes.DATE, description="Defaults to today")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        day = today()
        if request.query_params.get("date"):
            from django.utils.dateparse import parse_date

            day = parse_date(request.query_params["date"])
            if day is None:
                raise ValidationError({"date": "Use YYYY-MM-DD."})
        class_ids = teacher_classroom_ids(request.user) if request.user.role == TEACHER else None
        return Response(summary_for_day(request.user.school, day, class_ids))


class StudentAttendanceSummaryView(RoleAccessMixin, generics.GenericAPIView):
    read_roles = (PRINCIPAL, ADMIN, TEACHER)

    @extend_schema(
        tags=["attendance"],
        summary="One student's attendance totals for a term",
        parameters=[OpenApiParameter("term", OpenApiTypes.INT, description="Defaults to current term")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, student_id):
        students = Student.objects.filter(school=request.user.school)
        if request.user.role == TEACHER:
            students = students.filter(classroom_id__in=teacher_classroom_ids(request.user))
        student = students.filter(pk=student_id).first()
        if student is None:
            raise NotFound("Student not found.")
        term = resolve_term(request.user.school, request.query_params.get("term"))
        data = student_attendance_summary(student, term)
        data.update({"student": student.id, "term": {"id": term.id, "name": str(term)}})
        return Response(data)
