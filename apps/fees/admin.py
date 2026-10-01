from django.contrib import admin

from .models import FeeItem, FeeStructure, Invoice, InvoiceAdjustment, InvoiceLine, Payment, Receipt


class FeeItemInline(admin.TabularInline):
    model = FeeItem
    extra = 0


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ("__str__", "school", "term", "level")
    list_filter = ("school", "term", "level")
    inlines = [FeeItemInline]


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    can_delete = False
    readonly_fields = ("description", "amount_kobo")


class AdjustmentInline(admin.TabularInline):
    model = InvoiceAdjustment
    extra = 0
    can_delete = False
    readonly_fields = ("kind", "amount_kobo", "reason", "created_by", "created_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "student", "term", "status", "total_kobo", "amount_paid_kobo", "balance_kobo", "school")
    list_filter = ("school", "term", "status")
    search_fields = ("number", "student__first_name", "student__last_name", "student__admission_number")
    readonly_fields = ("subtotal_kobo", "adjustments_kobo", "total_kobo", "amount_paid_kobo", "balance_kobo", "status")
    inlines = [InvoiceLineInline, AdjustmentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "student", "amount_kobo", "method", "status", "paid_at", "school")
    list_filter = ("school", "method", "status")
    search_fields = ("reference", "external_reference", "student__last_name")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("number", "payment", "amount_kobo", "issued_at", "school")
    list_filter = ("school",)
    search_fields = ("number",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
