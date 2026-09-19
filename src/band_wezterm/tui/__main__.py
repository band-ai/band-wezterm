"""`python -m band_wezterm.tui` — run the Control tab in this pane."""

from __future__ import annotations

from band_wezterm.tui.control_app import run_control_app

if __name__ == "__main__":
    raise SystemExit(run_control_app())
