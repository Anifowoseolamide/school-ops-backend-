"""API error handling.

Errors keep DRF's standard shapes so any DRF-aware frontend works:

* Validation errors (400): ``{"field": ["message"], "non_field_errors": [...]}``
* Everything else: ``{"detail": "message", "code": "machine_code"}``

We add two mappings DRF does not do by default:

* Django ``ValidationError`` (raised in model/service code) becomes a 400.
* ``ProtectedError`` (deleting something other records depend on) becomes a 409.
"""
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler


class Conflict(exceptions.APIException):
    """The request is valid but conflicts with the current state (e.g. results already published)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This action conflicts with the current state of the record."
    default_code = "conflict"


class WorkflowError(Conflict):
    default_detail = "This action is not allowed at the current workflow stage."
    default_code = "workflow_error"


class PaymentGatewayError(exceptions.APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The payment provider could not be reached. Please try again."
    default_code = "payment_gateway_error"


def api_exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=as_serializer_error(exc))
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied(str(exc) or None)
    elif isinstance(exc, ProtectedError):
        return Response(
            {
                "detail": "This record cannot be deleted because other records depend on it. "
                "Deactivate or archive it instead.",
                "code": "protected",
            },
            status=status.HTTP_409_CONFLICT,
        )

    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" in response.data:
        code = getattr(exc, "default_code", None)
        detail_codes = getattr(exc, "get_codes", None)
        if callable(detail_codes):
            codes = detail_codes()
            if isinstance(codes, str):
                code = codes
        if code and "code" not in response.data:
            response.data["code"] = code
    return response
