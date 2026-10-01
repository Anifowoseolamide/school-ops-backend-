from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit log entries cannot be changed.")

    def delete(self):
        raise PermissionError("Audit log entries cannot be deleted.")


class AuditLog(models.Model):
    """Append-only record of who did what, when and from where."""

    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, null=True, blank=True, related_name="audit_logs"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs"
    )
    actor_email = models.CharField(max_length=254, blank=True)
    actor_role = models.CharField(max_length=20, blank=True)
    action = models.CharField(max_length=100, db_index=True, help_text="e.g. student.updated, payment.recorded")
    object_type = models.CharField(max_length=100, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["school", "-created_at"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email or 'system'} {self.action}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit log entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries cannot be deleted.")
