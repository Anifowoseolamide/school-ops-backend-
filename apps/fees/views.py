from datetime import date

import django_filters
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view, inline_serializer
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.exceptions import Conflict
from apps.core.permissions import RoleAccessMixin
from apps.core.roles import BURSAR, PRINCIPAL
from apps.core.viewsets import AuditedMixin, SchoolModelViewSet, SchoolScopedMixin
from apps.schools.services import resolve_term

from . import services
from .models import FeeStructure, Invoice, Payment, Receipt
from .pdf import render_receipt
from .serializers import (
    CancelSerializer,
    FeeStructureSerializer,
    InvoiceAdjustmentSerializer,
    InvoiceCreateSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    ManualPaymentSerializer,
    PaymentSerializer,
    ReverseSerializer,
)

FINANCE_READ = (PRINCIPAL, BURSAR)
FINANCE_WRITE = (BURSAR,)

GenerateResponse = inline_serializer(
    "GenerateInvoicesResponse",
    fields={
        "created": serializers.IntegerField(),
        "skipped_existing": serializers.IntegerField(),
        "students_at_level": serializers.IntegerField(),
    },
)
LinkResponse = inline_serializer("LinkResponse", fields={"url": serializers.URLField(), "expires_in_days": serializers.IntegerField()})
SentResponse = inline_serializer("SentResponse", fields={"detail": serializers.CharField(), "messages_sent": serializers.IntegerField()})


@extend_schema_view(
    list=extend_schema(tags=["fees"], summary="Fee structures (principal, bursar)"),
    retrieve=extend_schema(tags=["fees"]),
    create=extend_schema(tags=["fees"], summary="Create a fee structure with its items (bursar)"),
    update=extend_schema(tags=["fees"], summary="Edit a fee structure; items are replaced (bursar)"),
    partial_update=extend_schema(tags=["fees"]),
    destroy=extend_schema(tags=["fees"], summary="Delete a fee structure that has no invoices (bursar)"),
)
class FeeStructureViewSet(SchoolModelViewSet):
    queryset = FeeStructure.objects.select_related("term__session").prefetch_related("items")
    serializer_class = FeeStructureSerializer
    read_roles = FINANCE_READ
    write_roles = FINANCE_WRITE
    audit_label = "fee_structure"
    filterset_fields = ["term", "level"]

    def perform_destroy(self, instance):
        if instance.invoices.exclude(status="cancelled").exists():
            raise Conflict("Invoices have been generated from this structure. Cancel them first.")
        super().perform_destroy(instance)

    @extend_schema(
        tags=["fees"],
        summary="Create invoices for every active student at this level (bursar)",
        description="Safe to run again: students who already have an invoice for the term are skipped.",
        request=None,
        responses=GenerateResponse,
    )
    @action(detail=True, methods=["post"], url_path="generate-invoices")
    def generate_invoices(self, request, pk=None):
        structure = self.get_object()
        result = services.generate_invoices_for_structure(structure, request.user)
        record_audit(request, "invoice.generated", structure, metadata=result)
        return Response(result, status=status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK)


class InvoiceFilter(django_filters.FilterSet):
    level = django_filters.CharFilter(field_name="classroom__level")
    has_balance = django_filters.BooleanFilter(method="filter_has_balance")

    class Meta:
        model = Invoice
        fields = ["term", "classroom", "student", "status", "level", "has_balance"]

    def filter_has_balance(self, queryset, name, value):
        return queryset.filter(balance_kobo__gt=0) if value else queryset.filter(balance_kobo__lte=0)


@extend_schema_view(
    list=extend_schema(tags=["fees"], summary="Invoices with payment status (principal, bursar)"),
    retrieve=extend_schema(tags=["fees"], summary="Invoice with lines, adjustments and payments"),
    create=extend_schema(
        tags=["fees"], summary="Create a one-off invoice for a student (bursar)",
        request=InvoiceCreateSerializer, responses={201: InvoiceDetailSerializer},
    ),
)
class InvoiceViewSet(
    RoleAccessMixin,
    SchoolScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Invoices are never edited directly: use adjustments, payments or cancel."""

    queryset = Invoice.objects.select_related("student", "classroom", "term__session")
    read_roles = FINANCE_READ
    write_roles = FINANCE_WRITE
    filterset_class = InvoiceFilter
    search_fields = ["number", "student__first_name", "student__last_name", "student__admission_number"]
    ordering_fields = ["created_at", "balance_kobo", "total_kobo", "student__last_name", "number"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("lines", "adjustments__created_by", "payments__receipt")
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return InvoiceListSerializer
        if self.action == "create":
            return InvoiceCreateSerializer
        return InvoiceDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = InvoiceCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invoice = services.create_invoice(
            data["student"],
            data["term"],
            [(line["description"], line["amount_kobo"]) for line in data["lines"]],
            due_date=data.get("due_date"),
            notes=data.get("notes", ""),
            user=request.user,
        )
        record_audit(request, "invoice.created", invoice, metadata={"total_kobo": invoice.total_kobo})
        return Response(InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["fees"], summary="Add a discount, scholarship, waiver or surcharge (bursar)",
                   request=InvoiceAdjustmentSerializer, responses={201: InvoiceDetailSerializer})
    @action(detail=True, methods=["post"])
    def adjustments(self, request, pk=None):
        invoice = self.get_object()
        serializer = InvoiceAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = services.add_adjustment(invoice, user=request.user, **serializer.validated_data)
        record_audit(request, "invoice.adjusted", invoice, metadata={
            "kind": adjustment.kind, "amount_kobo": adjustment.amount_kobo, "reason": adjustment.reason,
        })
        invoice.refresh_from_db()
        return Response(InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["fees"], summary="Cancel an invoice with no payments (bursar)", request=CancelSerializer,
                   responses=InvoiceDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        invoice = self.get_object()
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = services.cancel_invoice(invoice, reason=serializer.validated_data["reason"], user=request.user)
        record_audit(request, "invoice.cancelled", invoice, metadata={"reason": invoice.cancel_reason})
        return Response(InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data)

    @extend_schema(tags=["fees"], summary="Get the parent pay link for this invoice", responses=LinkResponse)
    @action(detail=True, methods=["get"], url_path="pay-link")
    def pay_link(self, request, pk=None):
        from django.conf import settings

        invoice = self.get_object()
        return Response({"url": services.pay_link(invoice), "expires_in_days": settings.PAY_LINK_MAX_AGE_DAYS})

    @extend_schema(tags=["fees"], summary="Send the pay link to the student's guardians by SMS/email (bursar)",
                   request=None, responses=SentResponse)
    @action(detail=True, methods=["post"], url_path="send-pay-link")
    def send_pay_link(self, request, pk=None):
        invoice = self.get_object()
        if invoice.status == "cancelled":
            raise Conflict("This invoice is cancelled.")
        logs = services.send_pay_link(invoice, request.user)
        record_audit(request, "invoice.pay_link_sent", invoice, metadata={"messages": len(logs)})
        if not logs:
            return Response({"detail": "This student has no guardian phone number or email on file.", "messages_sent": 0},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Pay link sent.", "messages_sent": len(logs)})


class PaymentFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="paid_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="paid_at", lookup_expr="date__lte")
    term = django_filters.NumberFilter(field_name="invoice__term")
    classroom = django_filters.NumberFilter(field_name="invoice__classroom")

    class Meta:
        model = Payment
        fields = ["invoice", "student", "method", "status", "term", "classroom", "date_from", "date_to"]


@extend_schema_view(
    list=extend_schema(tags=["fees"], summary="Payments (principal, bursar)"),
    retrieve=extend_schema(tags=["fees"]),
    create=extend_schema(
        tags=["fees"], summary="Record a cash / transfer / POS / cheque payment (bursar)",
        request=ManualPaymentSerializer, responses={201: PaymentSerializer},
    ),
)
class PaymentViewSet(
    RoleAccessMixin,
    AuditedMixin,
    SchoolScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Payments can never be edited or deleted. Use `reverse` to undo one."""

    queryset = Payment.objects.select_related("invoice__classroom", "student", "recorded_by", "receipt")
    serializer_class = PaymentSerializer
    read_roles = FINANCE_READ
    write_roles = FINANCE_WRITE
    filterset_class = PaymentFilter
    search_fields = ["reference", "external_reference", "student__first_name", "student__last_name",
                     "student__admission_number", "invoice__number", "payer_name"]
    ordering_fields = ["paid_at", "amount_kobo", "created_at"]

    def create(self, request, *args, **kwargs):
        serializer = ManualPaymentSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = services.record_manual_payment(
            data["invoice"],
            amount_kobo=data["amount_kobo"],
            method=data["method"],
            paid_at=data.get("paid_at"),
            external_reference=data.get("external_reference", ""),
            payer_name=data.get("payer_name", ""),
            note=data.get("note", ""),
            user=request.user,
        )
        record_audit(request, "payment.recorded", payment, metadata={
            "amount_kobo": payment.amount_kobo, "method": payment.method, "invoice": payment.invoice.number,
            "receipt": payment.receipt.number,
        })
        payment = self.get_queryset().get(pk=payment.pk)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["fees"], summary="Reverse (refund/correct) a payment (bursar)", request=ReverseSerializer,
                   responses={201: PaymentSerializer})
    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payment = self.get_object()
        serializer = ReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reversal = services.reverse_payment(payment, reason=serializer.validated_data["reason"], user=request.user)
        record_audit(request, "payment.reversed", payment, metadata={
            "reversal_reference": reversal.reference, "amount_kobo": payment.amount_kobo,
            "reason": serializer.validated_data["reason"],
        })
        return Response(PaymentSerializer(reversal).data, status=status.HTTP_201_CREATED)

    def _receipt(self):
        payment = self.get_object()
        try:
            return payment.receipt
        except Receipt.DoesNotExist as exc:
            raise ValidationError("This payment has no receipt (it is pending, failed or a reversal).") from exc

    @extend_schema(tags=["fees"], summary="Download the receipt PDF", responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        receipt = self._receipt()
        response = HttpResponse(render_receipt(receipt), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{receipt.number}.pdf"'
        return response

    @extend_schema(tags=["fees"], summary="Shareable receipt link for parents", responses=LinkResponse)
    @action(detail=True, methods=["get"], url_path="receipt-link")
    def receipt_link(self, request, pk=None):
        from django.conf import settings

        receipt = self._receipt()
        return Response({"url": services.receipt_link(receipt), "expires_in_days": settings.RECEIPT_LINK_MAX_AGE_DAYS})

    @extend_schema(tags=["fees"], summary="Re-send the receipt to guardians (bursar)", request=None, responses=SentResponse)
    @action(detail=True, methods=["post"], url_path="send-receipt")
    def send_receipt(self, request, pk=None):
        payment = self.get_object()
        self._receipt()
        logs = services.send_receipt_notification(payment)
        record_audit(request, "payment.receipt_sent", payment, metadata={"messages": len(logs)})
        return Response({"detail": "Receipt sent." if logs else "No guardian contact on file.", "messages_sent": len(logs)})


class OutstandingReportView(RoleAccessMixin, generics.GenericAPIView):
    read_roles = FINANCE_READ

    @extend_schema(
        tags=["fees"],
        summary="Billed, collected and outstanding per class for a term",
        parameters=[OpenApiParameter("term", OpenApiTypes.INT, description="Defaults to the current term")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        term = resolve_term(request.user.school, request.query_params.get("term"))
        return Response(services.outstanding_by_class(request.user.school, term))


class CollectionsReportView(RoleAccessMixin, generics.GenericAPIView):
    read_roles = FINANCE_READ

    @extend_schema(
        tags=["fees"],
        summary="Money received by day and payment method",
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.DATE, description="Defaults to the 1st of this month"),
            OpenApiParameter("date_to", OpenApiTypes.DATE, description="Defaults to today"),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        today = timezone.localdate()
        date_from = parse_date(request.query_params.get("date_from", "")) or date(today.year, today.month, 1)
        date_to = parse_date(request.query_params.get("date_to", "")) or today
        if date_from > date_to:
            raise ValidationError("date_from must be before date_to.")
        return Response(services.collections_summary(request.user.school, date_from, date_to))
