"""Redacted, rotating diagnostics for host and managed-agent lifecycle events."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from band_wezterm.config import LOCAL_STATE_DIRNAME

LOGGER_NAME: Final = "band_wezterm"
LOG_FILENAME: Final = "diagnostics.log"
LOG_MAX_BYTES: Final = 1_000_000
LOG_BACKUP_COUNT: Final = 3
LOG_FORMAT: Final = "%(asctime)s %(levelname)s %(message)s"


def diagnostics_log_path(*, home: Path | None = None) -> Path:
    root = home if home is not None else Path.home()
    return root / LOCAL_STATE_DIRNAME / LOG_FILENAME


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
    """Record a useful failure summary without request headers, tokens, or traces."""
    logging.getLogger(LOGGER_NAME).error(
        "%s failed error_type=%s message=%s",
        operation,
        type(error).__name__,
        message,
    )
