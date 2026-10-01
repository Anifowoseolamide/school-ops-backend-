from django.db.models import Count, Q
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view, inline_serializer
from rest_framework import generics, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.exceptions import WorkflowError
from apps.core.permissions import RoleAccessMixin
from apps.core.roles import ADMIN, PRINCIPAL, TEACHER
from apps.core.viewsets import SchoolReadOnlyViewSet, SchoolScopedMixin
from apps.notifications.services import notify_guardians
from apps.schools.services import get_current_term, resolve_term

from . import services
from .models import ClassResult, ClassResultStatus, ResultSummary, ScoreSheet
from .report_cards import render_report_cards, report_card_link
from .serializers import (
    ClassResultSerializer,
    ResultSummarySerializer,
    ReturnSheetSerializer,
    ScoreBulkSerializer,
    ScoreSheetDetailSerializer,
    ScoreSheetListSerializer,
    SetupSerializer,
    UnlockSerializer,
)

LinkResponse = inline_serializer("ReportCardLinkResponse", fields={"url": serializers.URLField(), "expires_in_days": serializers.IntegerField()})
SetupResponse = inline_serializer(
    "ResultsSetupResponse",
    fields={
        "class_results_created": serializers.IntegerField(),
        "sheets_created": serializers.IntegerField(),
        "sheets_reassigned": serializers.IntegerField(),
    },
)


def pdf_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


class ResultsSetupView(RoleAccessMixin, generics.GenericAPIView):
    write_roles = (ADMIN,)
    serializer_class = SetupSerializer

    @extend_schema(
        tags=["results"],
        summary="Create class results and score sheets for a term from teacher assignments (admin)",
        description="Idempotent. Run again after adding classes or changing teacher assignments.",
        responses=SetupResponse,
    )
    def post(self, request):
        serializer = SetupSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        term = serializer.validated_data.get("term") or get_current_term(request.user.school)
        result = services.setup_term(term)
        record_audit(request, "results.setup", term, metadata=result)
        return Response(result)


@extend_schema_view(
    list=extend_schema(tags=["results"], summary="Score sheets (teachers see only their own)"),
    retrieve=extend_schema(tags=["results"], summary="Score sheet with one row per student"),
)
class ScoreSheetViewSet(SchoolReadOnlyViewSet):
    queryset = ScoreSheet.objects.select_related("classroom", "subject", "teacher", "term__session", "class_result", "school__settings")
    read_roles = (PRINCIPAL, ADMIN, TEACHER)
    action_roles = {
        "scores": (TEACHER,),
        "submit": (TEACHER,),
        "return_sheet": (ADMIN,),
    }
    filterset_fields = ["term", "classroom", "subject", "teacher", "status", "class_result"]
    ordering_fields = ["classroom__level_order", "subject__name", "status", "updated_at"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(teacher=self.request.user)
        return queryset

    def get_serializer_class(self):
        return ScoreSheetListSerializer if self.action == "list" else ScoreSheetDetailSerializer

    def _own_sheet(self):
        sheet = self.get_object()
        if sheet.teacher_id != self.request.user.id:
            raise PermissionDenied("Only the subject teacher can change this sheet.")
        return sheet

    @extend_schema(
        tags=["results"],
        summary="Save scores for several students at once (subject teacher)",
        description="Send only the fields you are changing. `null` clears a score.",
        request=ScoreBulkSerializer,
        responses=ScoreSheetDetailSerializer,
    )
    @action(detail=True, methods=["put", "patch"])
    def scores(self, request, pk=None):
        sheet = self._own_sheet()
        serializer = ScoreBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.save_scores(sheet, serializer.validated_data["scores"], request.user)
        record_audit(request, "scores.saved", sheet, metadata={"rows": len(serializer.validated_data["scores"])})
        sheet.refresh_from_db()
        return Response(ScoreSheetDetailSerializer(sheet, context=self.get_serializer_context()).data)

    @extend_schema(tags=["results"], summary="Submit the sheet for review (subject teacher)", request=None,
                   responses=ScoreSheetDetailSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        sheet = services.submit_sheet(self._own_sheet(), request.user)
        record_audit(request, "scores.submitted", sheet)
        return Response(ScoreSheetDetailSerializer(sheet, context=self.get_serializer_context()).data)

    @extend_schema(tags=["results"], summary="Return a submitted sheet to the teacher with a note (admin)",
                   request=ReturnSheetSerializer, responses=ScoreSheetDetailSerializer)
    @action(detail=True, methods=["post"], url_path="return")
    def return_sheet(self, request, pk=None):
        sheet = self.get_object()
        serializer = ReturnSheetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sheet = services.return_sheet(sheet, serializer.validated_data["note"], request.user)
        record_audit(request, "scores.returned", sheet, metadata={"note": sheet.return_note})
        return Response(ScoreSheetDetailSerializer(sheet, context=self.get_serializer_context()).data)


@extend_schema_view(
    list=extend_schema(tags=["results"], summary="Class results and their workflow status"),
    retrieve=extend_schema(tags=["results"]),
    partial_update=extend_schema(tags=["results"], summary="Set 'next term begins' date (principal, admin)"),
    update=extend_schema(tags=["results"], summary="Set 'next term begins' date (principal, admin)"),
)
class ClassResultViewSet(RoleAccessMixin, SchoolScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Teachers can read the class result of classes they are form teacher of (to write comments)."""

    queryset = ClassResult.objects.select_related("classroom", "term__session", "approved_by", "published_by")
    serializer_class = ClassResultSerializer
    read_roles = (PRINCIPAL, ADMIN, TEACHER)
    write_roles = (PRINCIPAL, ADMIN)
    action_roles = {
        "begin_review": (ADMIN,),
        "approve": (PRINCIPAL,),
        "send_back": (PRINCIPAL,),
        "publish": (PRINCIPAL,),
        "unlock": (PRINCIPAL,),
        "report_cards": (PRINCIPAL, ADMIN),
        "broadsheet": (PRINCIPAL, ADMIN),
        "send_report_cards": (PRINCIPAL, ADMIN),
    }
    filterset_fields = ["term", "classroom", "status"]

    def get_queryset(self):
        queryset = super().get_queryset().annotate(
            sheets_total=Count("sheets", distinct=True),
            sheets_submitted=Count("sheets", filter=Q(sheets__status="submitted"), distinct=True),
        ).order_by("term__start_date", "classroom__level_order", "classroom__arm")
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(classroom__class_teacher=self.request.user)
        return queryset

    def _transition(self, request, func, action_name, **extra):
        class_result = func(self.get_object(), request.user)
        record_audit(request, action_name, class_result, metadata=extra or None)
        return Response(self.get_serializer(self.get_queryset().get(pk=class_result.pk)).data)

    @extend_schema(tags=["results"], summary="Start review once every sheet is submitted (admin)", request=None)
    @action(detail=True, methods=["post"], url_path="begin-review")
    def begin_review(self, request, pk=None):
        return self._transition(request, services.begin_review, "results.review_started")

    @extend_schema(tags=["results"], summary="Approve the class results (principal)", request=None)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._transition(request, services.approve, "results.approved")

    @extend_schema(tags=["results"], summary="Send approved results back to review (principal)", request=None)
    @action(detail=True, methods=["post"], url_path="send-back")
    def send_back(self, request, pk=None):
        return self._transition(request, services.send_back, "results.sent_back")

    @extend_schema(tags=["results"], summary="Publish results; report cards become available to parents (principal)", request=None)
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._transition(request, services.publish, "results.published")

    @extend_schema(tags=["results"], summary="Reopen published results for correction (principal; reason required)",
                   request=UnlockSerializer)
    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        serializer = UnlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._transition(request, services.unlock, "results.unlocked", reason=serializer.validated_data["reason"])

    @extend_schema(tags=["results"], summary="Each student's total, average, position and comments",
                   responses=ResultSummarySerializer(many=True))
    @action(detail=True, methods=["get"])
    def summaries(self, request, pk=None):
        class_result = self.get_object()
        queryset = class_result.summaries.select_related("student", "class_result__classroom").order_by(
            "position", "student__last_name"
        )
        return Response(ResultSummarySerializer(queryset, many=True).data)

    @extend_schema(tags=["results"], summary="Broadsheet: every student's total in every subject",
                   responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["get"])
    def broadsheet(self, request, pk=None):
        class_result = self.get_object()
        sheets = list(class_result.sheets.select_related("subject").order_by("subject__name"))
        from .models import Score

        totals = {}
        for row in Score.objects.filter(sheet__class_result=class_result).values("student_id", "sheet_id", "total"):
            totals[(row["student_id"], row["sheet_id"])] = row["total"]
        summaries = {s.student_id: s for s in class_result.summaries.all()}
        students = services.sheet_students(sheets[0]) if sheets else []
        return Response({
            "class_result": class_result.id,
            "classroom": class_result.classroom.name,
            "term": str(class_result.term),
            "status": class_result.status,
            "subjects": [{"sheet": s.id, "subject": s.subject.name, "status": s.status} for s in sheets],
            "rows": [
                {
                    "student": st.id,
                    "full_name": st.full_name,
                    "admission_number": st.admission_number,
                    "totals": [totals.get((st.id, sh.id)) for sh in sheets],
                    "total": summaries[st.id].total if st.id in summaries else None,
                    "average": summaries[st.id].average if st.id in summaries else None,
                    "position": summaries[st.id].position if st.id in summaries else None,
                }
                for st in students
            ],
        })

    @extend_schema(
        tags=["results"],
        summary="All report cards for the class as one PDF (principal, admin)",
        description="Before publishing, the PDF is watermarked 'DRAFT - NOT PUBLISHED'.",
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="report-cards")
    def report_cards(self, request, pk=None):
        class_result = self.get_object()
        if class_result.status == ClassResultStatus.OPEN:
            raise WorkflowError("Start the review first so totals and positions are calculated.")
        summaries = list(class_result.summaries.select_related("student", "class_result__classroom", "class_result__term__session", "class_result__school__settings").order_by("student__last_name", "student__first_name"))
        content = render_report_cards(summaries, draft=class_result.status != ClassResultStatus.PUBLISHED)
        record_audit(request, "report_cards.generated", class_result, metadata={"count": len(summaries)})
        return pdf_response(content, f"report-cards-{class_result.classroom.name.replace(' ', '')}.pdf")

    @extend_schema(tags=["results"], summary="Send report card links to every guardian in the class (principal, admin)",
                   request=None, responses={200: OpenApiTypes.OBJECT})
    @action(detail=True, methods=["post"], url_path="send-report-cards")
    def send_report_cards(self, request, pk=None):
        class_result = self.get_object()
        if class_result.status != ClassResultStatus.PUBLISHED:
            raise WorkflowError("Publish the results before sending report cards.")
        sent = 0
        for summary in class_result.summaries.select_related("student", "class_result__term__session", "school"):
            message = (
                f"{summary.student.first_name}'s report card for {class_result.term} is ready: "
                f"{report_card_link(summary)} - {class_result.school.name}"
            )
            sent += len(notify_guardians(summary.student, "Report card", message, purpose="report_card", obj=summary,
                                         sent_by=request.user))
        record_audit(request, "report_cards.sent", class_result, metadata={"messages": sent})
        return Response({"detail": "Report card links sent.", "messages_sent": sent})


@extend_schema_view(
    retrieve=extend_schema(tags=["results"], summary="One student's result summary"),
    partial_update=extend_schema(
        tags=["results"],
        summary="Write comments",
        description="Class teacher: `class_teacher_comment`. Principal: `principal_comment`. Not allowed once published.",
    ),
)
class ResultSummaryViewSet(RoleAccessMixin, SchoolScopedMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = ResultSummary.objects.select_related("student", "class_result__classroom", "class_result__term__session",
                                                    "class_result__school__settings")
    serializer_class = ResultSummarySerializer
    read_roles = (PRINCIPAL, ADMIN, TEACHER)
    write_roles = (PRINCIPAL, TEACHER)
    action_roles = {"share_link": (PRINCIPAL, ADMIN)}
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        if self.request.user.role == TEACHER:
            queryset = queryset.filter(class_result__classroom__class_teacher=self.request.user)
        return queryset

    def partial_update(self, request, *args, **kwargs):
        summary = self.get_object()
        data = {k: request.data[k] for k in ("class_teacher_comment", "principal_comment") if k in request.data}
        serializer = self.get_serializer(summary, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        summary = services.update_comments(summary, request.user, serializer.validated_data)
        record_audit(request, "results.comment_updated", summary, metadata={"fields": list(data)})
        return Response(self.get_serializer(summary).data)

    @extend_schema(tags=["results"], summary="This student's report card PDF",
                   responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"], url_path="report-card")
    def report_card(self, request, pk=None):
        summary = self.get_object()
        content = render_report_cards([summary], draft=summary.class_result.status != ClassResultStatus.PUBLISHED)
        return pdf_response(content, f"report-card-{summary.student.admission_number}.pdf")

    @extend_schema(tags=["results"], summary="Shareable report card link for the parent (principal, admin)",
                   responses=LinkResponse)
    @action(detail=True, methods=["get"], url_path="share-link")
    def share_link(self, request, pk=None):
        from django.conf import settings

        summary = self.get_object()
        if summary.class_result.status != ClassResultStatus.PUBLISHED:
            raise WorkflowError("Results must be published before sharing report cards.")
        return Response({"url": report_card_link(summary), "expires_in_days": settings.REPORT_CARD_LINK_MAX_AGE_DAYS})


class MissingScoresView(RoleAccessMixin, generics.GenericAPIView):
    read_roles = (PRINCIPAL, ADMIN)

    @extend_schema(
        tags=["results"],
        summary="Score sheets not yet submitted, by teacher",
        parameters=[OpenApiParameter("term", OpenApiTypes.INT, description="Defaults to the current term")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        term = resolve_term(request.user.school, request.query_params.get("term"))
        return Response(services.missing_scores(request.user.school, term))
