import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.audit.services import record_audit
from apps.core.permissions import IsSchoolStaff, RoleAccessMixin
from apps.core.roles import ADMIN, PRINCIPAL
from apps.core.viewsets import AuditedMixin, SchoolScopedMixin
from apps.schools.services import get_current_session

from .models import User
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    MeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    StaffSerializer,
    generate_temporary_password,
)

logger = logging.getLogger(__name__)

DetailResponse = inline_serializer("DetailResponse", fields={"detail": serializers.CharField()})


@extend_schema(tags=["auth"], summary="Log in with email and password")
class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        email = (request.data.get("email") or "").strip().lower() if hasattr(request.data, "get") else ""
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            user = User.objects.filter(email__iexact=email).first() if email else None
            record_audit(
                request,
                "auth.login_failed",
                user,
                metadata={"email": email},
                actor=None,
                school=getattr(user, "school_id", None),
            )
            raise
        record_audit(request, "auth.login", serializer.user, actor=serializer.user)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@extend_schema(tags=["auth"], summary="Exchange a refresh token for a new access token")
class RefreshView(TokenRefreshView):
    pass


@extend_schema(tags=["auth"], summary="Log out (blacklists the refresh token)", responses={205: None})
class LogoutView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            pass  # already invalid: the user is effectively logged out
        record_audit(request, "auth.logout", request.user)
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema_view(
    get=extend_schema(tags=["auth"], summary="Current user's profile, role and capabilities"),
    patch=extend_schema(tags=["auth"], summary="Update own name and phone"),
    put=extend_schema(tags=["auth"], summary="Update own name and phone"),
)
class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsSchoolStaff]
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


@extend_schema(tags=["auth"], summary="Change own password", responses={200: DetailResponse})
class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        record_audit(request, "auth.password_changed", user)
        return Response({"detail": "Password changed."})


@extend_schema(
    tags=["auth"],
    summary="Request a password reset email",
    description="Always returns 200 so the endpoint cannot be used to discover which emails exist.",
    responses={200: DetailResponse},
)
class PasswordResetRequestView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = PasswordResetRequestSerializer
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            try:
                send_mail(
                    "Reset your password",
                    f"Hello {user.first_name},\n\nUse this link to set a new password:\n{link}\n\n"
                    "If you did not ask for this, you can ignore this email.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
            except Exception:  # pragma: no cover - mail outage should not leak details
                logger.exception("Password reset email failed for user %s", user.pk)
            record_audit(request, "auth.password_reset_requested", user, actor=user)
        return Response({"detail": "If that email belongs to an account, a reset link has been sent."})


@extend_schema(tags=["auth"], summary="Set a new password using the emailed reset link", responses={200: DetailResponse})
class PasswordResetConfirmView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = PasswordResetConfirmSerializer
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        record_audit(request, "auth.password_reset_completed", user, actor=user)
        return Response({"detail": "Password has been reset. You can now log in."})


TemporaryPasswordResponse = inline_serializer(
    "TemporaryPasswordResponse",
    fields={"detail": serializers.CharField(), "temporary_password": serializers.CharField()},
)


@extend_schema_view(
    list=extend_schema(tags=["staff"], summary="List staff (principal, admin)"),
    retrieve=extend_schema(tags=["staff"], summary="Staff details"),
    create=extend_schema(tags=["staff"], summary="Create a staff account (admin)"),
    update=extend_schema(tags=["staff"], summary="Edit a staff account (admin)"),
    partial_update=extend_schema(tags=["staff"], summary="Edit a staff account (admin)"),
)
class StaffViewSet(
    RoleAccessMixin,
    AuditedMixin,
    SchoolScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Staff accounts are never deleted (history must stay intact). Deactivate them instead."""

    queryset = User.objects.all()
    serializer_class = StaffSerializer
    read_roles = (PRINCIPAL, ADMIN)
    write_roles = (ADMIN,)
    audit_label = "staff"
    filterset_fields = ["role", "is_active"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    ordering_fields = ["first_name", "last_name", "role", "last_login", "date_joined"]

    def get_queryset(self):
        return super().get_queryset().prefetch_related("form_classes")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False) and self.request.user.is_authenticated:
            context["current_session"] = get_current_session(self.request.user.school)
        return context

    def _guard_target(self, user):
        if user.role == PRINCIPAL:
            raise PermissionDenied("The principal's account can only be changed by the platform operator.")
        if user.pk == self.request.user.pk:
            raise PermissionDenied("You cannot do this to your own account.")

    @extend_schema(tags=["staff"], summary="Deactivate a staff account (admin)", request=None, responses=StaffSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        self._guard_target(user)
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        record_audit(request, "staff.deactivated", user)
        return Response(self.get_serializer(user).data)

    @extend_schema(tags=["staff"], summary="Reactivate a staff account (admin)", request=None, responses=StaffSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        self._guard_target(user)
        user.is_active = True
        user.save(update_fields=["is_active", "updated_at"])
        record_audit(request, "staff.activated", user)
        return Response(self.get_serializer(user).data)

    @extend_schema(
        tags=["staff"],
        summary="Reset a staff member's password (admin)",
        description="Generates a temporary password, returned once. The user must change it at next login.",
        request=None,
        responses=TemporaryPasswordResponse,
    )
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        self._guard_target(user)
        temporary = generate_temporary_password()
        user.set_password(temporary)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password", "updated_at"])
        record_audit(request, "staff.password_reset", user)
        return Response({"detail": "Temporary password generated.", "temporary_password": temporary})
