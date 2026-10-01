from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.core.links import read_link_token
from apps.fees.models import Invoice, InvoiceStatus

from .models import ClassResultStatus, ResultSummary
from .report_cards import render_report_cards
from .views import pdf_response


class PublicReportCardView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "public_links"

    @extend_schema(
        tags=["public"],
        summary="Download a published report card from a signed link",
        description="Returns 403 if the school holds report cards for unpaid fees and the term invoice has a balance.",
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    def get(self, request, token):
        summary_id = read_link_token(token, "report_card", settings.REPORT_CARD_LINK_MAX_AGE_DAYS)
        summary = (
            ResultSummary.objects.select_related(
                "student", "class_result__classroom", "class_result__term__session", "class_result__school__settings"
            )
            .filter(pk=summary_id)
            .first()
        )
        if summary is None or summary.class_result.status != ClassResultStatus.PUBLISHED:
            raise NotFound("This report card is not available.")
        school_settings = summary.class_result.school.settings
        if school_settings.hold_report_cards_for_debtors:
            owing = Invoice.objects.filter(
                student=summary.student, term=summary.class_result.term, balance_kobo__gt=0
            ).exclude(status=InvoiceStatus.CANCELLED).exists()
            if owing:
                raise PermissionDenied(
                    "This report card is on hold because the term's fees have an outstanding balance. "
                    "Please contact the school."
                )
        return pdf_response(render_report_cards([summary]), f"report-card-{summary.student.admission_number}.pdf")
