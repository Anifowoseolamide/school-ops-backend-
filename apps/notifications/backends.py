"""SMS backends.

V1 ships a console backend (logs the message). To use a real provider
(Termii, Africa's Talking, Twilio...), write a class with a `send(to, message)`
method that returns the provider's message id, and point `SMS_BACKEND` at it.
"""
import logging
import uuid

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class BaseSMSBackend:
    def send(self, to: str, message: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSMSBackend(BaseSMSBackend):
    """Writes SMS messages to the log. `outbox` keeps them for tests."""

    outbox: list[dict] = []

    def send(self, to: str, message: str) -> str:
        reference = f"console-{uuid.uuid4().hex[:12]}"
        ConsoleSMSBackend.outbox.append({"to": to, "message": message, "reference": reference})
        logger.info("SMS to %s: %s", to, message)
        return reference


def get_sms_backend() -> BaseSMSBackend:
    return import_string(settings.SMS_BACKEND)()
