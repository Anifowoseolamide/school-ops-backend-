from django.urls import path

from .views import AdminDashboardView, BursarDashboardView, PrincipalDashboardView, TeacherDashboardView

urlpatterns = [
    path("principal/", PrincipalDashboardView.as_view(), name="dashboard-principal"),
    path("bursar/", BursarDashboardView.as_view(), name="dashboard-bursar"),
    path("admin/", AdminDashboardView.as_view(), name="dashboard-admin"),
    path("teacher/", TeacherDashboardView.as_view(), name="dashboard-teacher"),
]
