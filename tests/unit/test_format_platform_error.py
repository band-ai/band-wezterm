"""User-facing formatting for Fern ``ApiError`` dumps."""

from __future__ import annotations

from types import SimpleNamespace

from band_rest.core.api_error import ApiError

from band_wezterm.errors import (
    PLAN_REQUIRED_MESSAGE,
    format_platform_error,
)


def test_validation_name_taken() -> None:
    error = ApiError(
        status_code=422,
        headers={"content-type": "application/json", "date": "Sat"},
        body={
            "error": {
                "code": "validation_error",
                "message": "Validation failed",
                "details": {"name": ["has already been taken"]},
                "request_id": "req_1",
            }
        },
    )
    assert format_platform_error(error) == "Name has already been taken."
    assert "headers:" not in format_platform_error(error)


def test_plan_required() -> None:
    error = ApiError(
        status_code=403,
        body={
            "error": {
                "code": "plan_required",
                "message": "Plan required",
                "request_id": "req_2",
            }
        },
    )
    assert format_platform_error(error) == PLAN_REQUIRED_MESSAGE


def test_typed_error_body() -> None:
    error = ApiError(
        status_code=422,
        body=SimpleNamespace(
            error=SimpleNamespace(
                code="validation_error",
                message="Validation failed",
                details={"name": ["has already been taken"]},
            )
        ),
    )
    assert format_platform_error(error) == "Name has already been taken."


def test_generic_exception_passthrough() -> None:
    assert format_platform_error(RuntimeError("boom")) == "boom"
