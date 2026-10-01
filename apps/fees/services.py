"""Fee and payment business logic. Views call these; they never touch balances directly."""
import logging
import secrets
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Sum, When
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit.services import record_audit
from apps.core.exceptions import Conflict
from apps.core.links import make_link_token
from apps.core.models import next_sequence_value
from apps.core.money import format_naira
from apps.notifications.services import notify_guardians
from apps.schools.models import ClassRoom
from apps.schools.services import get_settings
from apps.students.models import Student, StudentStatus

from . import paystack
from .models import (
    MANUAL_METHODS,
    REDUCING_KINDS,
    Invoice,
    InvoiceAdjustment,
    InvoiceLine,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Receipt,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Numbers and references
# ---------------------------------------------------------------------------
def _invoice_number(school) -> str:
    prefix = get_settings(school).invoice_prefix or "INV"
    return f"{prefix}-{next_sequence_value(school, 'invoice'):06d}"


def _receipt_number(school) -> str:
    prefix = get_settings(school).receipt_prefix or "RCT"
    return f"{prefix}-{next_sequence_value(school, 'receipt'):06d}"


def new_payment_reference(prefix: str) -> str:
    return f"{prefix}-{timezone.now():%y%m%d}-{secrets.token_hex(5).upper()}"


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@transaction.atomic
def create_invoice(student, term, lines, *, structure=None, due_date=None, notes="", user=None) -> Invoice:
    """`lines` is a list of (description, amount_kobo)."""
    if student.school_id != term.school_id:
        raise ValidationError("Student and term belong to different schools.")
    if Invoice.objects.filter(student=student, term=term).exclude(status=InvoiceStatus.CANCELLED).exists():
        raise Conflict(f"{student.full_name} already has an invoice for {term}.")
    if not lines:
        raise ValidationError({"lines": "An invoice needs at least one line."})
    invoice = Invoice.objects.create(
        school=student.school,
        number=_invoice_number(student.school),
        student=student,
        term=term,
        classroom=student.classroom,
        structure=structure,
        due_date=due_date,
        notes=notes,
        created_by=user,
    )
    InvoiceLine.objects.bulk_create(
        [InvoiceLine(invoice=invoice, description=desc, amount_kobo=int(amount)) for desc, amount in lines]
    )
    invoice.recalculate()
    return invoice


def generate_invoices_for_structure(structure, user=None) -> dict:
    """Create the term invoice for every active student at the structure's class level.

    Safe to run again: students who already have an invoice for the term are skipped.
    """
    items = list(structure.items.all())
    if not items:
        raise ValidationError("Add at least one fee item before generating invoices.")
    lines = [(item.name, item.amount_kobo) for item in items]
    students = Student.objects.filter(
        school=structure.school, status=StudentStatus.ACTIVE, classroom__level=structure.level
    ).select_related("classroom")
    existing = set(
        Invoice.objects.filter(term=structure.term)
        .exclude(status=InvoiceStatus.CANCELLED)
        .values_list("student_id", flat=True)
    )
    created, skipped = 0, 0
    for student in students:
        if student.id in existing:
            skipped += 1
            continue
        create_invoice(
            student, structure.term, lines, structure=structure, due_date=structure.due_date, user=user
        )
        created += 1
    return {"created": created, "skipped_existing": skipped, "students_at_level": created + skipped}


@transaction.atomic
def add_adjustment(invoice, *, kind, amount_kobo, reason, user) -> InvoiceAdjustment:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise Conflict("This invoice is cancelled.")
    if amount_kobo <= 0:
        raise ValidationError({"amount_kobo": "Amount must be greater than zero."})
    if kind in REDUCING_KINDS and amount_kobo > invoice.total_kobo:
        raise ValidationError({"amount_kobo": "A discount cannot be larger than the invoice total."})
    adjustment = InvoiceAdjustment.objects.create(
        school=invoice.school, invoice=invoice, kind=kind, amount_kobo=amount_kobo, reason=reason, created_by=user
    )
    invoice.recalculate()
    return adjustment


@transaction.atomic
def cancel_invoice(invoice, *, reason, user) -> Invoice:
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise Conflict("This invoice is already cancelled.")
    if invoice.amount_paid_kobo != 0:
        raise Conflict("This invoice has payments. Reverse them before cancelling.")
    invoice.payments.filter(status=PaymentStatus.PENDING).update(status=PaymentStatus.FAILED)
    invoice.status = InvoiceStatus.CANCELLED
    invoice.cancelled_at = timezone.now()
    invoice.cancel_reason = reason
    invoice.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    return invoice


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def validate_payment_amount(invoice, amount_kobo: int, *, online: bool) -> None:
    if invoice.status == InvoiceStatus.CANCELLED:
        raise Conflict("This invoice is cancelled.")
    if amount_kobo is None or amount_kobo <= 0:
        raise ValidationError({"amount_kobo": "Amount must be greater than zero."})
    balance = invoice.balance_kobo
    if balance <= 0:
        raise Conflict("This invoice is already fully paid.")
    if amount_kobo > balance:
        raise ValidationError({"amount_kobo": f"Amount is more than the balance of {format_naira(balance)}."})
    if online and amount_kobo < balance:
        school_settings = get_settings(invoice.school)
        if not school_settings.allow_part_payment:
            raise ValidationError({"amount_kobo": "This school only accepts payment of the full balance online."})
        minimum = school_settings.minimum_part_payment_kobo
        if minimum and amount_kobo < minimum:
            raise ValidationError({"amount_kobo": f"The minimum part payment is {format_naira(minimum)}."})


def _issue_receipt(payment) -> Receipt:
    invoice = payment.invoice
    invoice.recalculate()
    return Receipt.objects.create(
        school=payment.school,
        payment=payment,
        number=_receipt_number(payment.school),
        issued_at=payment.paid_at or timezone.now(),
        amount_kobo=payment.amount_kobo,
        balance_after_kobo=invoice.balance_kobo,
    )


@transaction.atomic
def record_manual_payment(
    invoice, *, amount_kobo, method, user, paid_at=None, external_reference="", payer_name="", note=""
) -> Payment:
    """Record cash, bank transfer, POS or cheque money received by the bursar."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if method not in MANUAL_METHODS:
        raise ValidationError({"method": "Online payments are recorded automatically, not by hand."})
    validate_payment_amount(invoice, amount_kobo, online=False)
    external_reference = (external_reference or "").strip()
    if external_reference and Payment.objects.filter(
        school=invoice.school, method=method, external_reference__iexact=external_reference,
        status=PaymentStatus.SUCCESSFUL, reversal_of__isnull=True,
    ).exists():
        raise Conflict("A payment with this bank/teller reference has already been recorded.")
    if paid_at and paid_at > timezone.now():
        raise ValidationError({"paid_at": "Payment date cannot be in the future."})
    payment = Payment.objects.create(
        school=invoice.school,
        invoice=invoice,
        student=invoice.student,
        amount_kobo=amount_kobo,
        method=method,
        status=PaymentStatus.SUCCESSFUL,
        reference=new_payment_reference("MAN"),
        external_reference=external_reference,
        paid_at=paid_at or timezone.now(),
        payer_name=payer_name,
        note=note,
        recorded_by=user,
    )
    _issue_receipt(payment)
    return payment


def start_online_payment(invoice, *, email, amount_kobo=None, payer_name="", initiated_by=None) -> dict:
    """Create a pending payment and get a Paystack checkout URL for it."""
    amount = int(amount_kobo or invoice.balance_kobo)
    validate_payment_amount(invoice, amount, online=True)
    simulated = paystack.simulation_enabled() and not paystack.is_configured()
    if not simulated and not paystack.is_configured():
        raise paystack.PaymentsNotConfigured()
    reference = new_payment_reference("PSK")
    payment = Payment.objects.create(
        school=invoice.school,
        invoice=invoice,
        student=invoice.student,
        amount_kobo=amount,
        method=PaymentMethod.PAYSTACK,
        status=PaymentStatus.PENDING,
        reference=reference,
        payer_email=email,
        payer_name=payer_name,
        recorded_by=initiated_by,
    )
    if simulated:
        authorization_url = f"{settings.PAYSTACK_CALLBACK_URL}?reference={reference}&trxref={reference}&simulated=true"
        access_code = ""
    else:
        try:
            data = paystack.initialize_transaction(
                email=email,
                amount_kobo=amount,
                reference=reference,
                callback_url=settings.PAYSTACK_CALLBACK_URL,
                metadata={
                    "school_id": invoice.school_id,
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.number,
                    "student_id": invoice.student_id,
                    "payment_id": payment.id,
                    "custom_fields": [
                        {"display_name": "Student", "variable_name": "student", "value": invoice.student.full_name},
                        {"display_name": "Invoice", "variable_name": "invoice", "value": invoice.number},
                    ],
                },
            )
        except Exception:
            payment.status = PaymentStatus.FAILED
            payment.save(update_fields=["status", "updated_at"])
            raise
        authorization_url = data.get("authorization_url", "")
        access_code = data.get("access_code", "")
        payment.gateway_response = {"access_code": access_code}
        payment.save(update_fields=["gateway_response", "updated_at"])
    return {
        "reference": reference,
        "authorization_url": authorization_url,
        "access_code": access_code,
        "amount_kobo": amount,
        "public_key": settings.PAYSTACK_PUBLIC_KEY,
        "simulated": simulated,
    }


def _parse_paid_at(value):
    if not value:
        return timezone.now()
    parsed = parse_datetime(str(value).replace("Z", "+00:00")) if isinstance(value, str) else value
    if isinstance(parsed, datetime):
        return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    return timezone.now()


@transaction.atomic
def confirm_online_payment(reference: str, data: dict, *, source: str) -> Payment | None:
    """Apply a Paystack transaction result. Safe to call many times (idempotent)."""
    payment = (
        Payment.objects.select_for_update()
        .select_related("invoice", "student", "school")
        .filter(reference=reference, method=PaymentMethod.PAYSTACK)
        .first()
    )
    if payment is None:
        logger.warning("Paystack %s for unknown reference %s", source, reference)
        return None
    if payment.status == PaymentStatus.SUCCESSFUL:
        return payment
    gateway_status = data.get("status")
    if gateway_status != "success":
        if gateway_status in ("failed", "abandoned", "reversed"):
            payment.status = PaymentStatus.FAILED
            payment.gateway_response = {**payment.gateway_response, "status": gateway_status,
                                        "gateway_response": data.get("gateway_response")}
            payment.save(update_fields=["status", "gateway_response", "updated_at"])
        return payment

    paid_amount = int(data.get("amount") or 0)
    currency = data.get("currency") or "NGN"
    flags = {}
    if paid_amount != payment.amount_kobo:
        flags["expected_amount_kobo"] = payment.amount_kobo
    if currency != "NGN":
        flags["currency"] = currency
    payment.amount_kobo = paid_amount
    payment.status = PaymentStatus.SUCCESSFUL
    payment.paid_at = _parse_paid_at(data.get("paid_at") or data.get("paidAt"))
    payment.channel = (data.get("channel") or "")[:30]
    payment.external_reference = str(data.get("id") or "")[:100]
    payment.gateway_response = {
        **payment.gateway_response,
        "status": gateway_status,
        "gateway_response": data.get("gateway_response"),
        "channel": data.get("channel"),
        "currency": currency,
        "source": source,
        **({"flags": flags} if flags else {}),
    }
    payment.save()
    receipt = _issue_receipt(payment)
    record_audit(
        None,
        "payment.online_confirmed",
        payment,
        school=payment.school,
        metadata={"source": source, "amount_kobo": paid_amount, "receipt": receipt.number, **flags},
    )
    transaction.on_commit(lambda: send_receipt_notification(payment))
    return payment


def verify_online_payment(reference: str) -> Payment:
    """Ask Paystack for the result of a payment (used when the parent returns from checkout)."""
    payment = Payment.objects.filter(reference=reference, method=PaymentMethod.PAYSTACK).first()
    if payment is None:
        raise NotFound("Payment not found.")
    if payment.status != PaymentStatus.PENDING:
        return payment
    if paystack.simulation_enabled() and not paystack.is_configured():
        data = {
            "status": "success",
            "amount": payment.amount_kobo,
            "currency": "NGN",
            "channel": "simulated",
            "id": f"sim-{payment.id}",
            "paid_at": timezone.now().isoformat(),
        }
    else:
        data = paystack.verify_transaction(reference)
    return confirm_online_payment(reference, data, source="verify") or payment


@transaction.atomic
def reverse_payment(payment, *, reason, user) -> Payment:
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != PaymentStatus.SUCCESSFUL or payment.is_reversal:
        raise Conflict("Only successful payments can be reversed.")
    if Payment.objects.filter(reversal_of=payment).exists():
        raise Conflict("This payment has already been reversed.")
    reversal = Payment.objects.create(
        school=payment.school,
        invoice=payment.invoice,
        student=payment.student,
        amount_kobo=-payment.amount_kobo,
        method=payment.method,
        status=PaymentStatus.SUCCESSFUL,
        reference=new_payment_reference("REV"),
        external_reference=payment.reference,
        paid_at=timezone.now(),
        note=reason,
        recorded_by=user,
        reversal_of=payment,
    )
    payment.invoice.recalculate()
    return reversal


# ---------------------------------------------------------------------------
# Links and notifications
# ---------------------------------------------------------------------------
def pay_link(invoice) -> str:
    return f"{settings.FRONTEND_URL}/pay/{make_link_token('pay', invoice.id)}"


def receipt_link(receipt) -> str:
    return f"{settings.BACKEND_URL}/api/v1/public/receipts/{make_link_token('receipt', receipt.id)}/"


def send_pay_link(invoice, user=None):
    student = invoice.student
    message = (
        f"Dear parent, {student.first_name}'s fees for {invoice.term}: total {format_naira(invoice.total_kobo)}, "
        f"paid {format_naira(invoice.amount_paid_kobo)}, balance {format_naira(invoice.balance_kobo)}. "
        f"Pay securely: {pay_link(invoice)} - {invoice.school.name}"
    )
    return notify_guardians(student, f"School fees for {student.full_name}", message, purpose="pay_link", obj=invoice, sent_by=user)


def send_receipt_notification(payment):
    try:
        receipt = payment.receipt
    except Receipt.DoesNotExist:
        return []
    invoice = payment.invoice
    message = (
        f"Payment of {format_naira(payment.amount_kobo)} received for {payment.student.full_name}. "
        f"Receipt {receipt.number}: {receipt_link(receipt)} . Balance: {format_naira(invoice.balance_kobo)}. "
        f"- {payment.school.name}"
    )
    return notify_guardians(payment.student, f"Payment receipt {receipt.number}", message, purpose="receipt", obj=payment)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def outstanding_by_class(school, term) -> dict:
    rows = (
        Invoice.objects.filter(school=school, term=term)
        .exclude(status=InvoiceStatus.CANCELLED)
        .values("classroom_id")
        .annotate(
            invoices=Count("id"),
            billed=Sum("total_kobo"),
            collected=Sum("amount_paid_kobo"),
            outstanding=Sum(Case(When(balance_kobo__gt=0, then="balance_kobo"), default=0, output_field=IntegerField())),
            paid=Count("id", filter=Q(status=InvoiceStatus.PAID)),
            part_paid=Count("id", filter=Q(status=InvoiceStatus.PART_PAID)),
            unpaid=Count("id", filter=Q(status=InvoiceStatus.UNPAID)),
        )
    )
    classes = {c.id: c for c in ClassRoom.objects.filter(school=school)}
    result, totals = [], {"invoices": 0, "billed": 0, "collected": 0, "outstanding": 0, "paid": 0, "part_paid": 0, "unpaid": 0}
    for row in rows:
        classroom = classes.get(row["classroom_id"])
        billed = row["billed"] or 0
        collected = row["collected"] or 0
        entry = {
            "classroom": {"id": classroom.id, "name": classroom.name} if classroom else None,
            "level_order": classroom.level_order if classroom else 99,
            "invoices": row["invoices"],
            "billed_kobo": billed,
            "collected_kobo": collected,
            "outstanding_kobo": row["outstanding"] or 0,
            "collection_rate": round(collected * 100 / billed, 1) if billed else None,
            "paid": row["paid"],
            "part_paid": row["part_paid"],
            "unpaid": row["unpaid"],
        }
        result.append(entry)
        totals["invoices"] += row["invoices"]
        totals["billed"] += billed
        totals["collected"] += collected
        totals["outstanding"] += entry["outstanding_kobo"]
        totals["paid"] += row["paid"]
        totals["part_paid"] += row["part_paid"]
        totals["unpaid"] += row["unpaid"]
    result.sort(key=lambda r: (r["level_order"], r["classroom"]["name"] if r["classroom"] else ""))
    for r in result:
        r.pop("level_order")
    summary = {
        "invoices": totals["invoices"],
        "billed_kobo": totals["billed"],
        "collected_kobo": totals["collected"],
        "outstanding_kobo": totals["outstanding"],
        "collection_rate": round(totals["collected"] * 100 / totals["billed"], 1) if totals["billed"] else None,
        "paid": totals["paid"],
        "part_paid": totals["part_paid"],
        "unpaid": totals["unpaid"],
    }
    return {"term": {"id": term.id, "name": str(term)}, "totals": summary, "classes": result}


def collections_summary(school, date_from, date_to) -> dict:
    payments = Payment.objects.filter(
        school=school, status=PaymentStatus.SUCCESSFUL, paid_at__date__gte=date_from, paid_at__date__lte=date_to
    )
    by_method = {
        row["method"]: {"count": row["count"], "amount_kobo": row["amount"] or 0}
        for row in payments.values("method").annotate(count=Count("id"), amount=Sum("amount_kobo"))
    }
    from django.db.models.functions import TruncDate

    by_day = [
        {"date": row["day"].isoformat(), "count": row["count"], "amount_kobo": row["amount"] or 0}
        for row in payments.annotate(day=TruncDate("paid_at")).values("day").annotate(
            count=Count("id"), amount=Sum("amount_kobo")
        ).order_by("day")
    ]
    total = payments.aggregate(t=Sum("amount_kobo"), c=Count("id"))
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_kobo": total["t"] or 0,
        "count": total["c"],
        "by_method": by_method,
        "by_day": by_day,
    }
