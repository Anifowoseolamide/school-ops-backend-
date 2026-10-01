import secrets

from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.core.roles import ADMIN, PRINCIPAL, ROLE_CAPABILITIES, TEACHER, Role
from apps.schools.services import get_current_session

from .models import User


def generate_temporary_password() -> str:
    return secrets.token_urlsafe(9)


class SchoolBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    logo = serializers.ImageField(allow_null=True, required=False)


class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "role"]
        read_only_fields = fields


class MeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    school = SchoolBriefSerializer(read_only=True)
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "role",
            "role_label",
            "school",
            "capabilities",
            "must_change_password",
            "last_login",
        ]
        read_only_fields = ["id", "email", "role", "school", "must_change_password", "last_login"]

    def get_capabilities(self, obj) -> list[str]:
        return ROLE_CAPABILITIES.get(obj.role, [])


class LoginSerializer(TokenObtainPairSerializer):
    """Email + password login. Returns access/refresh tokens and the user profile."""

    default_error_messages = {
        "no_active_account": "Incorrect email or password.",
        "no_school": "This account is not linked to a school role.",
    }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["school_id"] = user.school_id
        return token

    def validate(self, attrs):
        attrs["email"] = (attrs.get("email") or "").strip().lower()
        data = super().validate(attrs)
        if not self.user.school_id or not self.user.role:
            raise serializers.ValidationError(self.error_messages["no_school"], code="no_school")
        data["user"] = MeSerializer(self.user).data
        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        password_validation.validate_password(attrs["new_password"], self.context["request"].user)
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError) as exc:
            raise serializers.ValidationError({"token": "This reset link is invalid or has expired."}) from exc
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "This reset link is invalid or has expired."})
        password_validation.validate_password(attrs["new_password"], user)
        attrs["user"] = user
        return attrs


class StaffSerializer(serializers.ModelSerializer):
    """Staff accounts. Admins create and edit staff; principals can only view."""

    full_name = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="Optional on create. If left out a temporary password is generated and returned once.",
    )
    temporary_password = serializers.SerializerMethodField()
    form_classes = serializers.SerializerMethodField()
    teaching = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "role",
            "role_label",
            "is_active",
            "must_change_password",
            "last_login",
            "date_joined",
            "form_classes",
            "teaching",
            "password",
            "temporary_password",
        ]
        read_only_fields = ["id", "is_active", "must_change_password", "last_login", "date_joined"]
        extra_kwargs = {"role": {"required": True}}

    def get_temporary_password(self, obj) -> str | None:
        return getattr(obj, "_temporary_password", None)

    def get_form_classes(self, obj) -> list[dict]:
        if obj.role != TEACHER:
            return []
        return [{"id": c.id, "name": c.name} for c in obj.form_classes.all()]

    def get_teaching(self, obj) -> list[dict]:
        if obj.role != TEACHER:
            return []
        session = self.context.get("current_session")
        if session is None and obj.school_id:
            session = get_current_session(obj.school)
            self.context["current_session"] = session
        if session is None:
            return []
        return [
            {
                "assignment_id": a.id,
                "classroom": {"id": a.classroom_id, "name": a.classroom.name},
                "subject": {"id": a.subject_id, "name": a.subject.name},
            }
            for a in obj.teaching_assignments.filter(session=session).select_related("classroom", "subject")
        ]

    def validate_email(self, value):
        value = value.strip().lower()
        queryset = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_role(self, value):
        request = self.context["request"]
        if value == Role.PRINCIPAL:
            raise serializers.ValidationError(
                "Principal accounts are created by the platform operator, not from the staff screen."
            )
        if self.instance is not None:
            if self.instance.role == PRINCIPAL:
                raise serializers.ValidationError("The principal's role cannot be changed here.")
            if self.instance.pk == request.user.pk and value != self.instance.role:
                raise serializers.ValidationError("You cannot change your own role.")
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.role == PRINCIPAL and self.context["request"].user.role == ADMIN:
            raise serializers.ValidationError("Admins cannot edit the principal's account.")
        password = attrs.get("password")
        if password:
            password_validation.validate_password(password)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password", "") or ""
        temporary = not password
        if temporary:
            password = generate_temporary_password()
        user = User.objects.create_user(password=password, must_change_password=temporary, **validated_data)
        if temporary:
            user._temporary_password = password
        return user

    def update(self, instance, validated_data):
        validated_data.pop("password", None)  # use the reset-password action instead
        return super().update(instance, validated_data)
