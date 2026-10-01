"""Public (no-login) endpoints reached through signed links sent to parents."""
from django.urls import include, path

urlpatterns = [
    path("", include("apps.fees.urls_public")),
    path("", include("apps.results.urls_public")),
]
