"""Endpoints parents reach through signed links, plus the Paystack webhook. No login."""
import json
import logging

from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record_audit
from apps.core.links import read_link_token

from . import paystack, services
from .models import Invoice, Payment, PaymentStatus, Receipt
from .pdf import render_receipt
from .serializers import (
    OnlinePaymentStartResponseSerializer,
    OnlinePaymentStartSerializer,
    PaymentStatusSerializer,
    PublicInvoiceSerializer,
)

logger = logging.getLogger(__name__)


class PublicAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "public_links"


def _invoice_from_token(token) -> Invoice:
    invoice_id = read_link_token(token, "pay", settings.PAY_LINK_MAX_AGE_DAYS)
    invoice = (
        Invoice.objects.select_related("school__settings", "student", "classroom", "term__session")
        .prefetch_related("lines")
        .filter(pk=invoice_id)
        .first()
    )
    if invoice is None or invoice.status == "cancelled":
        raise NotFound("This invoice is no longer available.")
    return invoice


class PublicInvoiceView(PublicAPIView):
    @extend_schema(tags=["public"], summary="Invoice summary for the parent pay page", responses=PublicInvoiceSerializer)
    def get(self, request, token):
        return Response(PublicInvoiceSerializer(_invoice_from_token(token)).data)


class PublicPaymentStartView(PublicAPIView):
    @extend_schema(
        tags=["public"],
        summary="Start an online payment; redirect the parent to authorization_url",
        request=OnlinePaymentStartSerializer,
        responses={201: OnlinePaymentStartResponseSerializer},
    )
    def post(self, request, token):
        invoice = _invoice_from_token(token)
        serializer = OnlinePaymentStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.start_online_payment(
            invoice,
            email=serializer.validated_data["email"],
            amount_kobo=serializer.validated_data.get("amount_kobo"),
            payer_name=serializer.validated_data.get("payer_name", ""),
        )
        record_audit(request, "payment.online_started", invoice, school=invoice.school_id,
                     metadata={"reference": result["reference"], "amount_kobo": result["amount_kobo"]})
        return Response(OnlinePaymentStartResponseSerializer(result).data, status=status.HTTP_201_CREATED)


def _status_payload(payment: Payment) -> dict:
    receipt = None
    try:
        receipt = payment.receipt
    except Receipt.DoesNotExist:
        pass
    payment.invoice.refresh_from_db()
    return {
        "reference": payment.reference,
        "status": payment.status,
        "amount_kobo": payment.amount_kobo,
        "paid_at": payment.paid_at,
        "receipt_number": receipt.number if receipt else None,
        "receipt_url": services.receipt_link(receipt) if receipt else None,
        "invoice_balance_kobo": payment.invoice.balance_kobo,
    }


class PublicPaymentVerifyView(PublicAPIView):
    @extend_schema(
        tags=["public"],
        summary="Check a payment after the parent returns from checkout",
        description="Call this from the Paystack callback page with the `reference` query parameter. "
        "It asks Paystack for the result, so it works even if the webhook is delayed.",
        parameters=[OpenApiParameter("reference", OpenApiTypes.STR, required=True)],
        responses=PaymentStatusSerializer,
    )
    def get(self, request):
        reference = request.query_params.get("reference") or request.query_params.get("trxref")
        if not reference:
            raise ValidationError({"reference": "This parameter is required."})
        payment = services.verify_online_payment(reference)
        return Response(PaymentStatusSerializer(_status_payload(payment)).data)


class PublicReceiptView(PublicAPIView):
    @extend_schema(tags=["public"], summary="Download a receipt PDF from a signed link",
                   responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request, token):
        receipt_id = read_link_token(token, "receipt", settings.RECEIPT_LINK_MAX_AGE_DAYS)
        receipt = Receipt.objects.select_related(
            "school", "payment__invoice__classroom", "payment__invoice__term__session", "payment__student"
        ).filter(pk=receipt_id).first()
        if receipt is None:
            raise NotFound("Receipt not found.")
        response = HttpResponse(render_receipt(receipt), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{receipt.number}.pdf"'
        return response


class PaystackWebhookView(APIView):
    """Paystack calls this on payment events. Configure the URL in the Paystack dashboard:
    https://<your-api-domain>/api/v1/payments/paystack/webhook/
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(tags=["fees"], summary="Paystack webhook (called by Paystack, not the frontend)",
                   request=OpenApiTypes.OBJECT, responses={200: None})
    def post(self, request):
        raw = request.body
        signature = request.META.get("HTTP_X_PAYSTACK_SIGNATURE")
        if not paystack.valid_signature(raw, signature):
            logger.warning("Rejected Paystack webhook with invalid signature")
            return Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            event = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)
        event_type = event.get("event")
        data = event.get("data") or {}
        reference = data.get("reference")
        if event_type == "charge.success" and reference:
            services.confirm_online_payment(reference, data, source="webhook")
        elif event_type in ("charge.failed",) and reference:
            Payment.objects.filter(reference=reference, status=PaymentStatus.PENDING).update(status=PaymentStatus.FAILED)
        # Always 200 for valid events so Paystack stops retrying.
        return Response({"received": True})
