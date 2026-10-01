"""Base view classes used by every app.

`SchoolModelViewSet` gives a standard REST resource that is:
* role-checked (see `apps.core.permissions`),
* limited to the requesting user's school,
* audited on create, update and delete.
"""
from rest_framework import mixins, viewsets

from apps.audit.services import record_audit

from .permissions import RoleAccessMixin
from .utils import diff, snapshot


class SchoolScopedMixin:
    """Filter querysets by the user's school and stamp the school on new records."""

    school_lookup = "school_id"

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):  # schema generation, no real user
            return queryset.none()
        return queryset.filter(**{self.school_lookup: self.request.user.school_id})

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = getattr(self.request, "user", None)
        context["school"] = getattr(user, "school", None) if user and user.is_authenticated else None
        return context


class AuditedMixin:
    """Write an audit log entry for create, update and destroy."""

    audit_label: str | None = None

    def get_audit_label(self) -> str:
        if self.audit_label:
            return self.audit_label
        model = self.get_queryset().model
        return model._meta.model_name

    def get_create_kwargs(self) -> dict:
        return {"school": self.request.user.school}

    def perform_create(self, serializer):
        instance = serializer.save(**self.get_create_kwargs())
        record_audit(self.request, f"{self.get_audit_label()}.created", instance, changes={"after": snapshot(instance)})

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = diff(before, snapshot(instance))
        if changes:
            record_audit(self.request, f"{self.get_audit_label()}.updated", instance, changes=changes)

    def perform_destroy(self, instance):
        before = snapshot(instance)
        record_audit(self.request, f"{self.get_audit_label()}.deleted", instance, changes={"before": before})
        instance.delete()


class SchoolModelViewSet(RoleAccessMixin, AuditedMixin, SchoolScopedMixin, viewsets.ModelViewSet):
    """Full CRUD resource for school-owned models."""


class SchoolReadOnlyViewSet(RoleAccessMixin, SchoolScopedMixin, viewsets.ReadOnlyModelViewSet):
    """List/retrieve-only resource for school-owned models."""


class SchoolCreateListRetrieveViewSet(
    RoleAccessMixin,
    AuditedMixin,
    SchoolScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """For records that are never edited or deleted once created (e.g. payments)."""
