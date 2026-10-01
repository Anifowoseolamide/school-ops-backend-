from rest_framework.routers import DefaultRouter

from .views import GuardianViewSet, StudentImportViewSet, StudentViewSet

router = DefaultRouter()
router.register("students/imports", StudentImportViewSet, basename="student-import")
router.register("students", StudentViewSet, basename="student")
router.register("guardians", GuardianViewSet, basename="guardian")

urlpatterns = router.urls
