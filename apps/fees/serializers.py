from django.db import transaction
from rest_framework import serializers

from apps.core.fields import SchoolPK
from apps.schools.models import Term
from apps.students.models import Student

from .models import (
    MANUAL_METHOD_CHOICES,
    AdjustmentKind,
    FeeItem,
    FeeStructure,
    Invoice,
    InvoiceAdjustment,
    InvoiceLine,
    Payment,
    Receipt,
)


class FeeItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeItem
        fields = ["id", "name", "amount_kobo", "position"]
        read_only_fields = ["id"]


class FeeStructureSerializer(serializers.ModelSerializer):
    term = SchoolPK(queryset=Term.objects.all())
    term_name = serializers.CharField(source="term.__str__", read_only=True)
    level_label = serializers.CharField(source="get_level_display", read_only=True)
    items = FeeItemSerializer(many=True)
    total_kobo = serializers.IntegerField(read_only=True)
    invoice_count = serializers.SerializerMethodField()

    class Meta:
        model = FeeStructure
        fields = [
            "id",
            "term",
            "term_name",
            "level",
            "level_label",
            "name",
            "notes",
            "due_date",
            "items",
            "total_kobo",
            "invoice_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_invoice_count(self, obj) -> int:
        return obj.invoices.exclude(status="cancelled").count()

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("Add at least one fee item.")
        return items

    def validate(self, attrs):
        term = attrs.get("term", getattr(self.instance, "term", None))
        level = attrs.get("level", getattr(self.instance, "level", None))
        qs = FeeStructure.objects.filter(term=term, level=level)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A fee structure already exists for this class level and term.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items")
        structure = FeeStructure.objects.create(**validated_data)
        FeeItem.objects.bulk_create([FeeItem(structure=structure, **item) for item in items])
        return structure

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        instance = super().update(instance, validated_data)
        if items is not None:
            instance.items.all().delete()
            FeeItem.objects.bulk_create([FeeItem(structure=instance, **item) for item in items])
        return instance


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ["id", "description", "amount_kobo"]
        read_only_fields = ["id"]


class InvoiceAdjustmentSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    signed_amount_kobo = serializers.IntegerField(read_only=True)

    class Meta:
        model = InvoiceAdjustment
        fields = ["id", "kind", "amount_kobo", "signed_amount_kobo", "reason", "created_by", "created_by_name", "created_at"]
        read_only_fields = ["id", "signed_amount_kobo", "created_by", "created_by_name", "created_at"]

    def validate_kind(self, value):
        if value not in AdjustmentKind.values:
            raise serializers.ValidationError("Unknown adjustment kind.")
        return value


class PaymentBriefSerializer(serializers.ModelSerializer):
    receipt_number = serializers.SerializerMethodField()
    method_label = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "reference", "amount_kobo", "method", "method_label", "status", "paid_at", "receipt_number", "reversal_of"]
        read_only_fields = fields

    def get_receipt_number(self, obj) -> str | None:
        try:
            return obj.receipt.number
        except Receipt.DoesNotExist:
            return None


class InvoiceListSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True, default=None)
    term_name = serializers.CharField(source="term.__str__", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            "student",
            "student_name",
            "admission_number",
            "classroom",
            "classroom_name",
            "term",
            "term_name",
            "status",
            "status_label",
            "total_kobo",
            "amount_paid_kobo",
            "balance_kobo",
            "due_date",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(InvoiceListSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    adjustments = InvoiceAdjustmentSerializer(many=True, read_only=True)
    payments = PaymentBriefSerializer(many=True, read_only=True)

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + [
            "subtotal_kobo",
            "adjustments_kobo",
            "notes",
            "lines",
            "adjustments",
            "payments",
            "cancelled_at",
            "cancel_reason",
        ]
        read_only_fields = fields


class InvoiceCreateSerializer(serializers.Serializer):
    """Create a one-off invoice for a single student (e.g. a late admission)."""

    student = SchoolPK(queryset=Student.objects.all())
    term = SchoolPK(queryset=Term.objects.all())
    lines = InvoiceLineSerializer(many=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one line.")
        for line in value:
            if line["amount_kobo"] <= 0:
                raise serializers.ValidationError("Line amounts must be greater than zero.")
        return value


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    classroom_name = serializers.CharField(source="invoice.classroom.name", read_only=True, default=None)
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.full_name", read_only=True, default=None)
    receipt_number = serializers.SerializerMethodField()
    is_reversed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "reference",
            "invoice",
            "invoice_number",
            "student",
            "student_name",
            "admission_number",
            "classroom_name",
            "amount_kobo",
            "method",
            "method_label",
            "status",
            "channel",
            "external_reference",
            "paid_at",
            "payer_name",
            "payer_email",
            "note",
            "recorded_by",
            "recorded_by_name",
            "receipt_number",
            "reversal_of",
            "is_reversed",
            "created_at",
        ]
        read_only_fields = fields

    def get_receipt_number(self, obj) -> str | None:
        try:
            return obj.receipt.number
        except Receipt.DoesNotExist:
            return None


class ManualPaymentSerializer(serializers.Serializer):
    invoice = SchoolPK(queryset=Invoice.objects.all())
    amount_kobo = serializers.IntegerField(min_value=1)
    method = serializers.ChoiceField(choices=MANUAL_METHOD_CHOICES)
    paid_at = serializers.DateTimeField(required=False)
    external_reference = serializers.CharField(required=False, allow_blank=True, max_length=100,
                                               help_text="Bank teller / transfer reference, if any")
    payer_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class OnlinePaymentStartSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Payer's email, required by Paystack for the receipt")
    amount_kobo = serializers.IntegerField(min_value=100, required=False,
                                           help_text="Defaults to the full balance")
    payer_name = serializers.CharField(required=False, allow_blank=True, max_length=150)


class OnlinePaymentStartResponseSerializer(serializers.Serializer):
    reference = serializers.CharField()
    authorization_url = serializers.URLField()
    access_code = serializers.CharField(allow_blank=True)
    amount_kobo = serializers.IntegerField()
    public_key = serializers.CharField(allow_blank=True)
    simulated = serializers.BooleanField()


class PublicInvoiceSerializer(serializers.ModelSerializer):
    """What a parent sees on the pay page. No internal IDs beyond what is needed."""

    school = serializers.SerializerMethodField()
    student = serializers.SerializerMethodField()
    term = serializers.CharField(source="term.__str__")
    lines = InvoiceLineSerializer(many=True)
    allow_part_payment = serializers.SerializerMethodField()
    minimum_part_payment_kobo = serializers.SerializerMethodField()
    online_payments_available = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "number",
            "school",
            "student",
            "term",
            "status",
            "lines",
            "subtotal_kobo",
            "adjustments_kobo",
            "total_kobo",
            "amount_paid_kobo",
            "balance_kobo",
            "due_date",
            "allow_part_payment",
            "minimum_part_payment_kobo",
            "online_payments_available",
        ]

    def get_school(self, obj) -> dict:
        return {"name": obj.school.name, "phone": obj.school.phone, "email": obj.school.email}

    def get_student(self, obj) -> dict:
        return {
            "name": obj.student.full_name,
            "admission_number": obj.student.admission_number,
            "classroom": obj.classroom.name if obj.classroom_id else None,
        }

    def get_allow_part_payment(self, obj) -> bool:
        return obj.school.settings.allow_part_payment

    def get_minimum_part_payment_kobo(self, obj) -> int:
        return obj.school.settings.minimum_part_payment_kobo

    def get_online_payments_available(self, obj) -> bool:
        from . import paystack

        return paystack.is_configured() or paystack.simulation_enabled()


class PaymentStatusSerializer(serializers.Serializer):
    reference = serializers.CharField()
    status = serializers.CharField()
    amount_kobo = serializers.IntegerField()
    paid_at = serializers.DateTimeField(allow_null=True)
    receipt_number = serializers.CharField(allow_null=True)
    receipt_url = serializers.CharField(allow_null=True)
    invoice_balance_kobo = serializers.IntegerField()
