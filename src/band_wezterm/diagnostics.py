"""Redacted, rotating diagnostics for host and managed-agent lifecycle events."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from band_wezterm.config import Settings, load_settings

LOGGER_NAME: Final = "band_wezterm"
LOG_FILENAME: Final = "diagnostics.log"
LOG_MAX_BYTES: Final = 1_000_000
LOG_BACKUP_COUNT: Final = 3
LOG_FORMAT: Final = "%(asctime)s %(levelname)s %(message)s"
DEFAULT_LOG_TAIL_LINES: Final = 100


def diagnostics_log_path(
    *, home: Path | None = None, settings: Settings | None = None
) -> Path:
    if home is not None:
        return home / ".band-wezterm" / LOG_FILENAME
    return (settings or load_settings()).local_state_path(LOG_FILENAME)


def configure_diagnostics(*, path: Path | None = None) -> None:
    """Send concise operational events to a local rotating log once per process."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    target = path or diagnostics_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            target,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, **context: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in sorted(context.items()))
    logging.getLogger(LOGGER_NAME).info("%s%s", event, f" {details}" if details else "")


def log_failure(operation: str, error: BaseException, message: str) -> None:
    """Record a redacted failure summary and traceback for incident diagnosis."""
    logging.getLogger(LOGGER_NAME).exception(
        "%s failed error_type=%s message=%s",
        operation,
        type(error).__name__,
        message,
    )


def read_diagnostics(*, lines: int = DEFAULT_LOG_TAIL_LINES) -> str:
    """Return the latest local events for incident triage without shell tooling."""
    if lines < 1:
        raise ValueError("--tail must be at least 1.")
    try:
        content = diagnostics_log_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return "No Band diagnostics have been recorded yet."
    except OSError as error:
        return f"Unable to read Band diagnostics: {type(error).__name__}."
    return (
        "\n".join(content.splitlines()[-lines:])
        or "No Band diagnostics have been recorded yet."
    )
