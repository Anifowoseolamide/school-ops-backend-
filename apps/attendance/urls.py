from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttendanceRecordViewSet, DailySummaryView, RegisterView, StudentAttendanceSummaryView

router = DefaultRouter()
router.register("records", AttendanceRecordViewSet, basename="attendance-record")

urlpatterns = [
    path("register/", RegisterView.as_view(), name="attendance-register"),
    path("summary/", DailySummaryView.as_view(), name="attendance-summary"),
    path("students/<int:student_id>/summary/", StudentAttendanceSummaryView.as_view(), name="attendance-student-summary"),
] + router.urls
