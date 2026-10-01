from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView


def health(_request):
    return JsonResponse({"status": "ok"})


api_v1 = [
    path("auth/", include("apps.accounts.urls_auth")),
    path("staff/", include("apps.accounts.urls_staff")),
    path("", include("apps.schools.urls")),
    path("", include("apps.students.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("fees/", include("apps.fees.urls")),
    path("results/", include("apps.results.urls")),
    path("audit/", include("apps.audit.urls")),
    path("dashboards/", include("apps.dashboards.urls")),
    path("public/", include("apps.core.urls_public")),
    path("payments/", include("apps.fees.urls_webhooks")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "School Operations Platform"
admin.site.site_title = "School Operations admin"
