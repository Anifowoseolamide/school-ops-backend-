from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AcademicSessionViewSet,
    ClassRoomViewSet,
    GradeBandViewSet,
    SchoolProfileView,
    SchoolSettingsView,
    SubjectViewSet,
    TeacherAssignmentViewSet,
    TermViewSet,
)

router = DefaultRouter()
router.register("sessions", AcademicSessionViewSet, basename="session")
router.register("terms", TermViewSet, basename="term")
router.register("classes", ClassRoomViewSet, basename="classroom")
router.register("subjects", SubjectViewSet, basename="subject")
router.register("assignments", TeacherAssignmentViewSet, basename="assignment")
router.register("grade-bands", GradeBandViewSet, basename="grade-band")

urlpatterns = [
    path("school/", SchoolProfileView.as_view(), name="school-profile"),
    path("school/settings/", SchoolSettingsView.as_view(), name="school-settings"),
] + router.urls
