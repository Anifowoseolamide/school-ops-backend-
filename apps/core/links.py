"""Signed, expiring tokens for links that parents open without logging in.

Tokens are signed with SECRET_KEY, carry a timestamp and are checked against a
maximum age, so they cannot be guessed, forged or used forever.
"""
from datetime import timedelta

from django.core import signing
from rest_framework.exceptions import NotFound

SALT_PREFIX = "schoolops.link."


def make_link_token(kind: str, object_id: int) -> str:
    return signing.dumps({"k": kind, "id": int(object_id)}, salt=SALT_PREFIX + kind, compress=True)


def read_link_token(token: str, kind: str, max_age_days: int) -> int:
    """Return the object id inside `token`, or raise 404 if it is invalid or expired."""
    try:
        data = signing.loads(token, salt=SALT_PREFIX + kind, max_age=timedelta(days=max_age_days))
    except signing.SignatureExpired as exc:
        raise NotFound("This link has expired. Please ask the school for a new one.") from exc
    except signing.BadSignature as exc:
        raise NotFound("This link is not valid.") from exc
    if data.get("k") != kind or "id" not in data:
        raise NotFound("This link is not valid.")
    return int(data["id"])
