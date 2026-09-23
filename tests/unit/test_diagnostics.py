"""Durable, bounded incident diagnostics."""

from __future__ import annotations

import logging

from band_wezterm import diagnostics


def test_diagnostics_rotate_and_are_readable(
    tmp_path, monkeypatch
) -> None:
    logger = logging.getLogger(diagnostics.LOGGER_NAME)
    original_handlers = logger.handlers[:]
    logger.handlers.clear()
    target = tmp_path / "diagnostics.log"
    monkeypatch.setattr(diagnostics, "LOG_MAX_BYTES", 80)
    monkeypatch.setattr(diagnostics, "LOG_BACKUP_COUNT", 1)
    monkeypatch.setattr(diagnostics, "diagnostics_log_path", lambda: target)
    try:
        diagnostics.configure_diagnostics(path=target)
        diagnostics.log_event("first event", resource_id="one")
        diagnostics.log_event("second event", resource_id="two")
        for handler in logger.handlers:
            handler.flush()
        assert target.with_suffix(".log.1").exists()
        assert "second event" in diagnostics.read_diagnostics(lines=10)
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = original_handlers
