import json
from datetime import date, datetime
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.fields.files import FieldFile
from django.forms.models import model_to_dict

# Fields we never copy into audit snapshots.
SENSITIVE_FIELDS = {"password", "secret", "token"}


def client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FieldFile):
        return value.name or None
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "pk"):
        return value.pk
    return value


def snapshot(instance) -> dict:
    """A JSON-safe dict of a model instance's concrete fields (for the audit log)."""
    if instance is None:
        return {}
    data = model_to_dict(instance)
    result = {}
    for key, value in data.items():
        if any(s in key for s in SENSITIVE_FIELDS):
            continue
        result[key] = _jsonable(value)
    # Make sure it really is JSON serialisable
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))


def diff(before: dict, after: dict) -> dict:
    """Return {field: {"from": x, "to": y}} for fields that changed."""
    changes = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changes[key] = {"from": before.get(key), "to": after.get(key)}
    return changes
