"""Unit tests for this process's WezTerm pane identity."""

from __future__ import annotations

import pytest

from band_wezterm.tui.host_pane import (
    WEZTERM_PANE_ENV,
    current_pane_id,
    current_window_id,
)
from band_wezterm.wezterm_cli import PaneId, WindowId


def test_current_pane_id_reads_wezterm_pane_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WEZTERM_PANE_ENV, "42")
    assert current_pane_id() == PaneId(42)


def test_current_pane_id_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WEZTERM_PANE_ENV, raising=False)
    assert current_pane_id() is None


def test_current_pane_id_none_when_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WEZTERM_PANE_ENV, "not-an-id")
    assert current_pane_id() is None


def test_current_window_id_resolves_from_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WEZTERM_PANE_ENV, "7")
    monkeypatch.setattr(
        "band_wezterm.tui.host_pane.window_id_for_pane",
        lambda pane_id: WindowId(99) if pane_id == PaneId(7) else None,
    )
    assert current_window_id() == WindowId(99)
