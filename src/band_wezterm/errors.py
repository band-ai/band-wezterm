"""User-facing platform error text — port of band-plugin-vsc ``infra/errors.ts``.

Fern ``ApiError.__str__`` dumps ``headers: …`` first; a one-line status bar
truncates before ``status_code`` / ``body``, so registration failures look like
raw HTTP metadata. Format like the extension instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from band_rest.core.api_error import ApiError

from band_wezterm.diagnostics import log_failure

PLAN_REQUIRED_STATUS: Final = 403
PLAN_REQUIRED_ERROR_CODE: Final = "plan_required"
PLAN_REQUIRED_MESSAGE: Final = (
    "This Band account doesn't have API access enabled — it requires an "
    "Enterprise plan. Contact your Band admin to enable it."
)

VALIDATION_STATUS: Final = 422
VALIDATION_ERROR_CODE: Final = "validation_error"


def _error_payload(body: Any) -> Mapping[str, Any] | None:
    if body is None:
        return None
    if isinstance(body, Mapping):
        error = body.get("error")
        return error if isinstance(error, Mapping) else None
    error = getattr(body, "error", None)
    if error is None:
        return None
    if isinstance(error, Mapping):
        return error
    return {
        "code": getattr(error, "code", None),
        "message": getattr(error, "message", None),
        "details": getattr(error, "details", None),
    }


def _field_label(field: str) -> str:
    leaf = field.rsplit(".", 1)[-1]
    words = leaf.replace("_", " ")
    return words[:1].upper() + words[1:] if words else field


def _validation_message(error: ApiError) -> str | None:
    if error.status_code != VALIDATION_STATUS:
        return None
    payload = _error_payload(error.body)
    if payload is None or payload.get("code") != VALIDATION_ERROR_CODE:
        return None
    details = payload.get("details")
    if not isinstance(details, Mapping):
        return None
    sentences: list[str] = []
    for field, messages in details.items():
        if isinstance(messages, list) and messages:
            joined = ", ".join(str(item) for item in messages)
            sentences.append(f"{_field_label(str(field))} {joined}.")
    return " ".join(sentences) if sentences else None


def format_platform_error(
    error: BaseException, *, operation: str = "Band operation"
) -> str:
    """Turn a caught exception into short Control-tab status text."""
    message = _platform_error_message(error)
    log_failure(operation, error, message)
    return message


def _platform_error_message(error: BaseException) -> str:
    if not isinstance(error, ApiError):
        return str(error)
    payload = _error_payload(error.body)
    if (
        error.status_code == PLAN_REQUIRED_STATUS
        and payload is not None
        and payload.get("code") == PLAN_REQUIRED_ERROR_CODE
    ):
        return PLAN_REQUIRED_MESSAGE
    validation = _validation_message(error)
    if validation:
        return validation
    if payload is not None:
        payload_message = payload.get("message")
        if payload_message:
            return str(payload_message)
        code = payload.get("code")
        if code:
            return f"HTTP {error.status_code}: {code}"
    return f"HTTP {error.status_code}" if error.status_code is not None else str(error)
