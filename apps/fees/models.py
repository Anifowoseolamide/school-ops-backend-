"""Fees, invoices and payments.

Money rules
-----------
* Every amount is an integer number of kobo. No floats anywhere.
* An invoice's total, amount paid, balance and status are *derived* from its
  lines, adjustments and successful payments by `Invoice.recalculate()`. They
  are stored only so lists and dashboards are fast; nobody types them in.
* Payments are never edited or deleted. A refund or correction is a new
  negative "reversal" payment that points at the original.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

from apps.core.models import SchoolOwnedModel, TimeStampedModel
from apps.schools.models import ClassLevel


class FeeStructure(SchoolOwnedModel):
    """What a class level pays in a term, e.g. JSS 1, First Term 2026/2027."""

    term = models.ForeignKey("schools.Term", on_delete=models.PROTECT, related_name="fee_structures")
    level = models.CharField(max_length=5, choices=ClassLevel.choices)
    name = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["term", "level"]
        constraints = [models.UniqueConstraint(fields=["term", "level"], name="uniq_fee_structure_per_level_term")]

    def __str__(self):
        return self.name or f"{self.get_level_display()} - {self.term}"

    @property
    def total_kobo(self) -> int:
        return sum(item.amount_kobo for item in self.items.all())


class FeeItem(TimeStampedModel):
    structure = models.ForeignKey(FeeStructure, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=100, help_text="e.g. Tuition, Books, Uniform")
    amount_kobo = models.PositiveBigIntegerField()
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.name}: {self.amount_kobo}"


class InvoiceStatus(models.TextChoices):
    UNPAID = "unpaid", "Owing"
    PART_PAID = "part_paid", "Part-paid"
    PAID = "paid", "Paid"
    CANCELLED = "cancelled", "Cancelled"


class Invoice(SchoolOwnedModel):
    number = models.CharField(max_length=30)
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="invoices")
    term = models.ForeignKey("schools.Term", on_delete=models.PROTECT, related_name="invoices")
    classroom = models.ForeignKey(
        "schools.ClassRoom", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices",
        help_text="The student's class when the invoice was issued.",
    )
    structure = models.ForeignKey(FeeStructure, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=InvoiceStatus.choices, default=InvoiceStatus.UNPAID, db_index=True)

    # Derived values, maintained by recalculate()
    subtotal_kobo = models.BigIntegerField(default=0)
    adjustments_kobo = models.BigIntegerField(default=0, help_text="Net adjustments: negative = discounts")
    total_kobo = models.BigIntegerField(default=0)
    amount_paid_kobo = models.BigIntegerField(default=0)
    balance_kobo = models.BigIntegerField(default=0)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["school", "number"], name="uniq_invoice_number_per_school"),
            models.UniqueConstraint(
                fields=["student", "term"],
                condition=~Q(status="cancelled"),
                name="uniq_open_invoice_per_student_term",
            ),
        ]
        indexes = [models.Index(fields=["school", "term", "status"])]

    def __str__(self):
        return f"{self.number} - {self.student.full_name}"

    def recalculate(self, save: bool = True):
        subtotal = self.lines.aggregate(t=Sum("amount_kobo"))["t"] or 0
        adjustments = 0
        for adj in self.adjustments.all():
            adjustments += adj.signed_amount_kobo
        total = max(subtotal + adjustments, 0)
        paid = self.payments.filter(status=PaymentStatus.SUCCESSFUL).aggregate(t=Sum("amount_kobo"))["t"] or 0
        self.subtotal_kobo = subtotal
        self.adjustments_kobo = adjustments
        self.total_kobo = total
        self.amount_paid_kobo = paid
        self.balance_kobo = total - paid
        if self.status != InvoiceStatus.CANCELLED:
            if self.balance_kobo <= 0:
                self.status = InvoiceStatus.PAID
            elif paid > 0:
                self.status = InvoiceStatus.PART_PAID
            else:
                self.status = InvoiceStatus.UNPAID
        if save:
            self.save(
                update_fields=[
                    "subtotal_kobo",
                    "adjustments_kobo",
                    "total_kobo",
                    "amount_paid_kobo",
                    "balance_kobo",
                    "status",
                    "updated_at",
                ]
            )
        return self


class InvoiceLine(TimeStampedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=150)
    amount_kobo = models.PositiveBigIntegerField()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.description}: {self.amount_kobo}"


class AdjustmentKind(models.TextChoices):
    DISCOUNT = "discount", "Discount"
    SCHOLARSHIP = "scholarship", "Scholarship"
    WAIVER = "waiver", "Waiver"
    SURCHARGE = "surcharge", "Surcharge / extra charge"


REDUCING_KINDS = (AdjustmentKind.DISCOUNT, AdjustmentKind.SCHOLARSHIP, AdjustmentKind.WAIVER)


class InvoiceAdjustment(SchoolOwnedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="adjustments")
    kind = models.CharField(max_length=15, choices=AdjustmentKind.choices)
    amount_kobo = models.PositiveBigIntegerField()
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount_kobo} on {self.invoice_id}"

    @property
    def signed_amount_kobo(self) -> int:
        return -self.amount_kobo if self.kind in REDUCING_KINDS else self.amount_kobo


class PaymentMethod(models.TextChoices):
    PAYSTACK = "paystack", "Online (Paystack)"
    CASH = "cash", "Cash"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    POS = "pos", "POS"
    CHEQUE = "cheque", "Cheque"


MANUAL_METHODS = (PaymentMethod.CASH, PaymentMethod.BANK_TRANSFER, PaymentMethod.POS, PaymentMethod.CHEQUE)
MANUAL_METHOD_CHOICES = [(m.value, m.label) for m in MANUAL_METHODS]


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCESSFUL = "successful", "Successful"
    FAILED = "failed", "Failed"


class Payment(SchoolOwnedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, related_name="payments")
    amount_kobo = models.BigIntegerField(help_text="Negative for reversals")
    method = models.CharField(max_length=15, choices=PaymentMethod.choices)
    status = models.CharField(max_length=12, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    reference = models.CharField(max_length=100, unique=True, help_text="Our unique reference")
    external_reference = models.CharField(
        max_length=100, blank=True, help_text="Bank/teller reference or the payment provider's transaction id"
    )
    channel = models.CharField(max_length=30, blank=True, help_text="Provider channel, e.g. card, bank_transfer, ussd")
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)
    payer_name = models.CharField(max_length=150, blank=True)
    payer_email = models.EmailField(blank=True)
    note = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reversal_of = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal"
    )
    gateway_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-paid_at", "-created_at"]
        indexes = [models.Index(fields=["school", "status", "paid_at"])]

    def __str__(self):
        return f"{self.reference} {self.amount_kobo} ({self.status})"

    @property
    def is_reversal(self) -> bool:
        return self.reversal_of_id is not None

    @property
    def is_reversed(self) -> bool:
        return hasattr(self, "reversal") and self.reversal is not None


class Receipt(SchoolOwnedModel):
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    number = models.CharField(max_length=30)
    issued_at = models.DateTimeField()
    amount_kobo = models.BigIntegerField()
    balance_after_kobo = models.BigIntegerField(help_text="Invoice balance right after this payment")

    class Meta:
        ordering = ["-issued_at"]
        constraints = [models.UniqueConstraint(fields=["school", "number"], name="uniq_receipt_number_per_school")]

    def __str__(self):
        return self.number
