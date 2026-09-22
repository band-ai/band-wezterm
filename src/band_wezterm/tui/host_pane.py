"""This process's WezTerm pane identity (``WEZTERM_PANE``)."""

from __future__ import annotations

import os
from typing import Final

from band_wezterm.wezterm_cli import PaneId, WindowId, window_id_for_pane

WEZTERM_PANE_ENV: Final = "WEZTERM_PANE"


def current_pane_id() -> PaneId | None:
    pane = os.environ.get(WEZTERM_PANE_ENV)
    if not pane:
        return None
    try:
        return PaneId(int(pane))
    except ValueError:
        return None


def current_window_id() -> WindowId | None:
    """Resolve the window from the pane this process was spawned into."""
    pane_id = current_pane_id()
    if pane_id is None:
        return None
    try:
        return window_id_for_pane(pane_id)
    except Exception:
        return None
