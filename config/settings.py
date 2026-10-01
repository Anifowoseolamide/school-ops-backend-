"""
Django settings for the School Operations Platform backend.

All environment-specific values come from environment variables (or a local
`.env` file). See `.env.example` for the full list.
"""
import sys
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .env import env_bool, env_int, env_list, env_str, load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent
load_env_file(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", True)
_DEV_SECRET = "django-insecure-dev-key-change-me-before-deploying"
SECRET_KEY = env_str("DJANGO_SECRET_KEY", _DEV_SECRET)
if not DEBUG and SECRET_KEY == _DEV_SECRET:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    # Project apps
    "apps.core",
    "apps.accounts",
    "apps.schools",
    "apps.students",
    "apps.attendance",
    "apps.fees",
    "apps.results",
    "apps.audit",
    "apps.notifications",
    "apps.dashboards",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database: SQLite by default, PostgreSQL when DB_ENGINE=postgres
# ---------------------------------------------------------------------------
DB_ENGINE = env_str("DB_ENGINE", "sqlite").lower()
if DB_ENGINE in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env_str("DB_NAME", "schoolops"),
            "USER": env_str("DB_USER", "schoolops"),
            "PASSWORD": env_str("DB_PASSWORD", ""),
            "HOST": env_str("DB_HOST", "localhost"),
            "PORT": env_str("DB_PORT", "5432"),
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / env_str("SQLITE_PATH", "db.sqlite3"),
            "OPTIONS": {
                # Wait for locks instead of failing immediately under light concurrency.
                "timeout": 20,
            },
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-gb"
TIME_ZONE = env_str("DJANGO_TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static and media files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / env_str("MEDIA_DIR", "media")
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# Django REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # Session auth lets developers use the browsable API after logging in at /admin/.
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env_str("THROTTLE_ANON", "120/minute"),
        "user": env_str("THROTTLE_USER", "2000/minute"),
        "login": env_str("THROTTLE_LOGIN", "10/minute"),
        "password_reset": env_str("THROTTLE_PASSWORD_RESET", "5/hour"),
        "public_links": env_str("THROTTLE_PUBLIC_LINKS", "60/minute"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 30)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "School Operations Platform API",
    "DESCRIPTION": (
        "Role-based backend for secondary school operations: students, staff, "
        "attendance, fees and payments, results and report cards. "
        "All money amounts are integers in kobo (100 kobo = 1 naira)."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "ENUM_NAME_OVERRIDES": {
        "StudentStatusEnum": "apps.students.models.StudentStatus",
        "InvoiceStatusEnum": "apps.fees.models.InvoiceStatus",
        "PaymentStatusEnum": "apps.fees.models.PaymentStatus",
        "PaymentMethodEnum": "apps.fees.models.PaymentMethod",
        "ManualPaymentMethodEnum": "apps.fees.models.MANUAL_METHOD_CHOICES",
        "SheetStatusEnum": "apps.results.models.SheetStatus",
        "ClassResultStatusEnum": "apps.results.models.ClassResultStatus",
        "AttendanceStatusEnum": "apps.attendance.models.AttendanceStatus",
        "ImportStatusEnum": "apps.students.models.ImportStatus",
    },
    "TAGS": [
        {"name": "auth", "description": "Login, tokens, profile and passwords"},
        {"name": "staff", "description": "Staff accounts (admin manages, principal views)"},
        {"name": "school", "description": "School profile, settings, sessions, terms, classes, subjects"},
        {"name": "students", "description": "Students, guardians and Excel/CSV import"},
        {"name": "attendance", "description": "Daily class registers"},
        {"name": "fees", "description": "Fee structures, invoices, payments and receipts"},
        {"name": "results", "description": "Score sheets, approval workflow and report cards"},
        {"name": "dashboards", "description": "One dashboard per role"},
        {"name": "audit", "description": "Append-only audit log (principal only)"},
        {"name": "public", "description": "Signed links for parents (no login)"},
    ],
}

# ---------------------------------------------------------------------------
# CORS (the frontend runs on a different origin during development)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)

# ---------------------------------------------------------------------------
# Email and SMS
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env_str("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env_str("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env_str("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL", "no-reply@schoolops.local")
SMS_BACKEND = env_str("SMS_BACKEND", "apps.notifications.backends.ConsoleSMSBackend")

# ---------------------------------------------------------------------------
# Product settings
# ---------------------------------------------------------------------------
# Base URL of the frontend app. Used to build pay links, password reset links, etc.
FRONTEND_URL = env_str("FRONTEND_URL", "http://localhost:3000").rstrip("/")
# Base URL of this API, used for links that point straight at the backend (PDF downloads).
BACKEND_URL = env_str("BACKEND_URL", "http://localhost:8000").rstrip("/")

PAYSTACK_SECRET_KEY = env_str("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = env_str("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_BASE_URL = env_str("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/")
PAYSTACK_CALLBACK_URL = env_str("PAYSTACK_CALLBACK_URL", f"{FRONTEND_URL}/payments/complete")
PAYSTACK_TIMEOUT_SECONDS = env_int("PAYSTACK_TIMEOUT_SECONDS", 20)
# Development only: lets the frontend complete "online" payments without Paystack keys.
# Ignored unless DJANGO_DEBUG is true.
PAYSTACK_SIMULATE = env_bool("PAYSTACK_SIMULATE", False)

PAY_LINK_MAX_AGE_DAYS = env_int("PAY_LINK_MAX_AGE_DAYS", 30)
RECEIPT_LINK_MAX_AGE_DAYS = env_int("RECEIPT_LINK_MAX_AGE_DAYS", 180)
REPORT_CARD_LINK_MAX_AGE_DAYS = env_int("REPORT_CARD_LINK_MAX_AGE_DAYS", 14)
IMPORT_MAX_ROWS = env_int("IMPORT_MAX_ROWS", 5000)

# ---------------------------------------------------------------------------
# Security (production)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Tests: fast password hashing, no rate limits, files in a temp folder
# ---------------------------------------------------------------------------
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {k: "100000/minute" for k in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]}
    MEDIA_ROOT = BASE_DIR / ".test-media"
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env_str("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        # Expected 4xx responses in tests would otherwise flood the output.
        "django.request": {"level": "ERROR" if TESTING else "WARNING"},
        "apps": {"level": "ERROR" if TESTING else "INFO"},
    },
}
