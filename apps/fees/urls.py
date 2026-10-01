from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CollectionsReportView, FeeStructureViewSet, InvoiceViewSet, OutstandingReportView, PaymentViewSet

router = DefaultRouter()
router.register("structures", FeeStructureViewSet, basename="fee-structure")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path("reports/outstanding/", OutstandingReportView.as_view(), name="fees-report-outstanding"),
    path("reports/collections/", CollectionsReportView.as_view(), name="fees-report-collections"),
] + router.urls
