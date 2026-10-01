from django.urls import path

from .views_public import PublicInvoiceView, PublicPaymentStartView, PublicPaymentVerifyView, PublicReceiptView

urlpatterns = [
    path("pay/<str:token>/", PublicInvoiceView.as_view(), name="public-invoice"),
    path("pay/<str:token>/initialize/", PublicPaymentStartView.as_view(), name="public-payment-start"),
    path("payments/verify/", PublicPaymentVerifyView.as_view(), name="public-payment-verify"),
    path("receipts/<str:token>/", PublicReceiptView.as_view(), name="public-receipt"),
]
