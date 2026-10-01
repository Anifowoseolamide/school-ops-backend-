from django.conf import settings
from django.db import models

from apps.core.models import SchoolOwnedModel


class Channel(models.TextChoices):
    SMS = "sms", "SMS"
    EMAIL = "email", "Email"


class DeliveryStatus(models.TextChoices):
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class NotificationLog(SchoolOwnedModel):
    """Every SMS or email the platform sends, for support and accountability."""

    channel = models.CharField(max_length=10, choices=Channel.choices)
    recipient = models.CharField(max_length=254)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=DeliveryStatus.choices)
    provider_reference = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    purpose = models.CharField(max_length=50, blank=True, help_text="e.g. pay_link, receipt, report_card")
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} to {self.recipient} ({self.status})"
