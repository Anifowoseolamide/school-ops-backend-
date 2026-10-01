"""Minimal Paystack client.

Docs: https://paystack.com/docs/api/transaction/
* initialize: POST /transaction/initialize  -> authorization_url for the parent
* verify:     GET  /transaction/verify/:reference
* webhooks:   POST to our endpoint, signed with HMAC-SHA512 of the raw body
              using the secret key, in the `x-paystack-signature` header.
"""
import hashlib
import hmac
import logging

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

from apps.core.exceptions import PaymentGatewayError

logger = logging.getLogger(__name__)


class PaymentsNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Online payments are not set up for this school yet. Please pay at the school."
    default_code = "payments_not_configured"


def is_configured() -> bool:
    return bool(settings.PAYSTACK_SECRET_KEY)


def simulation_enabled() -> bool:
    """Local development without Paystack keys (never in production)."""
    return settings.DEBUG and getattr(settings, "PAYSTACK_SIMULATE", False)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}


def _request(method: str, path: str, **kwargs) -> dict:
    if not is_configured():
        raise PaymentsNotConfigured()
    url = f"{settings.PAYSTACK_BASE_URL}{path}"
    try:
        response = requests.request(
            method, url, headers=_headers(), timeout=settings.PAYSTACK_TIMEOUT_SECONDS, **kwargs
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.exception("Paystack request failed: %s %s", method, path)
        raise PaymentGatewayError() from exc
    if response.status_code >= 400 or not payload.get("status"):
        logger.warning("Paystack error %s on %s: %s", response.status_code, path, payload.get("message"))
        raise PaymentGatewayError(payload.get("message") or "Payment provider error.")
    return payload.get("data") or {}


def initialize_transaction(*, email: str, amount_kobo: int, reference: str, callback_url: str, metadata: dict) -> dict:
    return _request(
        "POST",
        "/transaction/initialize",
        json={
            "email": email,
            "amount": int(amount_kobo),
            "currency": "NGN",
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata,
        },
    )


def verify_transaction(reference: str) -> dict:
    return _request("GET", f"/transaction/verify/{reference}")


def valid_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature or not is_configured():
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
