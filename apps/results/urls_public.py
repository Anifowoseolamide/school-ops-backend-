from django.urls import path

from .views_public import PublicReportCardView

urlpatterns = [
    path("report-cards/<str:token>/", PublicReportCardView.as_view(), name="public-report-card"),
]
