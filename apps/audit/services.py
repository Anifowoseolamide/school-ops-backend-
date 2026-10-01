"""Write audit log entries.

Call `record_audit(request, "thing.happened", obj, changes={...})` from views or
services whenever something important happens. It never raises: a failure to
audit is logged, but does not break the user's action.
"""
import logging

from apps.core.utils import client_ip

logger = logging.getLogger(__name__)


def _school_id_for(obj, user, school):
    if school is not None:
        return getattr(school, "pk", school)
    if obj is not None:
        if obj.__class__.__name__ == "School" and obj._meta.app_label == "schools":
            return obj.pk
        sid = getattr(obj, "school_id", None)
        if sid:
            return sid
    return getattr(user, "school_id", None)


def record_audit(request, action, obj=None, *, changes=None, metadata=None, actor=None, school=None):
    from .models import AuditLog

    try:
        user = actor
        if user is None and request is not None:
            candidate = getattr(request, "user", None)
            if candidate is not None and candidate.is_authenticated:
                user = candidate
        return AuditLog.objects.create(
            school_id=_school_id_for(obj, user, school),
            actor=user,
            actor_email=getattr(user, "email", "") or "",
            actor_role=getattr(user, "role", "") or "",
            action=action,
            object_type=obj._meta.label_lower if obj is not None else "",
            object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
            object_repr=str(obj)[:255] if obj is not None else "",
            changes=changes or {},
            metadata=metadata or {},
            ip_address=client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request is not None else ""),
        )
    except Exception:  # pragma: no cover - auditing must never break the request
        logger.exception("Failed to write audit log entry for action %s", action)
        return None
