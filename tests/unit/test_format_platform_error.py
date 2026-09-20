"""User-facing formatting for Fern ``ApiError`` dumps."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from band_rest.core.api_error import ApiError

from band_wezterm.errors import (
    PLAN_REQUIRED_MESSAGE,
    format_platform_error,
    is_missing_resource,
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


def test_is_missing_resource_recognizes_platform_not_found() -> None:
    assert is_missing_resource(ApiError(status_code=404))
    assert not is_missing_resource(ApiError(status_code=500))
    assert not is_missing_resource(RuntimeError("not found"))


def test_error_is_logged_with_its_operation(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger="band_wezterm"):
        assert (
            format_platform_error(RuntimeError("offline"), operation="load rooms")
            == "offline"
        )

    assert "load rooms failed error_type=RuntimeError message=offline" in caplog.text
