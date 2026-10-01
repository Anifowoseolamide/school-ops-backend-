import logging

from django.conf import settings
from django.core.mail import EmailMessage

from .backends import get_sms_backend
from .models import Channel, DeliveryStatus, NotificationLog

logger = logging.getLogger(__name__)


def _log(school, channel, recipient, body, *, subject="", status, reference="", error="", purpose="", obj=None, sent_by=None):
    return NotificationLog.objects.create(
        school=school,
        channel=channel,
        recipient=recipient,
        subject=subject[:200],
        body=body,
        status=status,
        provider_reference=reference,
        error=error,
        purpose=purpose,
        object_type=obj._meta.label_lower if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        sent_by=sent_by,
    )


def send_sms(school, to: str, message: str, *, purpose="", obj=None, sent_by=None) -> NotificationLog:
    try:
        reference = get_sms_backend().send(to, message)
        return _log(school, Channel.SMS, to, message, status=DeliveryStatus.SENT, reference=reference or "",
                    purpose=purpose, obj=obj, sent_by=sent_by)
    except Exception as exc:  # pragma: no cover - provider failure
        logger.exception("SMS to %s failed", to)
        return _log(school, Channel.SMS, to, message, status=DeliveryStatus.FAILED, error=str(exc),
                    purpose=purpose, obj=obj, sent_by=sent_by)


def send_email(school, to: str, subject: str, message: str, *, attachments=None, purpose="", obj=None, sent_by=None) -> NotificationLog:
    try:
        email = EmailMessage(subject, message, settings.DEFAULT_FROM_EMAIL, [to])
        for name, content, mimetype in attachments or []:
            email.attach(name, content, mimetype)
        email.send(fail_silently=False)
        return _log(school, Channel.EMAIL, to, message, subject=subject, status=DeliveryStatus.SENT,
                    purpose=purpose, obj=obj, sent_by=sent_by)
    except Exception as exc:  # pragma: no cover - mail failure
        logger.exception("Email to %s failed", to)
        return _log(school, Channel.EMAIL, to, message, subject=subject, status=DeliveryStatus.FAILED,
                    error=str(exc), purpose=purpose, obj=obj, sent_by=sent_by)


def notify_guardians(student, subject: str, message: str, *, purpose="", obj=None, sent_by=None) -> list[NotificationLog]:
    """Send `message` to each of the student's guardians by email (if known) and SMS (if known)."""
    logs = []
    for guardian in student.guardians.all():
        if guardian.email:
            logs.append(send_email(student.school, guardian.email, subject, message, purpose=purpose, obj=obj, sent_by=sent_by))
        if guardian.phone:
            logs.append(send_sms(student.school, guardian.phone, message, purpose=purpose, obj=obj, sent_by=sent_by))
    return logs
