from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ClassResultViewSet, MissingScoresView, ResultsSetupView, ResultSummaryViewSet, ScoreSheetViewSet

router = DefaultRouter()
router.register("sheets", ScoreSheetViewSet, basename="score-sheet")
router.register("class-results", ClassResultViewSet, basename="class-result")
router.register("summaries", ResultSummaryViewSet, basename="result-summary")

urlpatterns = [
    path("setup/", ResultsSetupView.as_view(), name="results-setup"),
    path("missing/", MissingScoresView.as_view(), name="results-missing"),
] + router.urls
