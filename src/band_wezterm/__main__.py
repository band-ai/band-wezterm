"""`band-wezterm` entrypoint — open the band workspace, or be the Control tab."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from band_wezterm.tui.control_app import is_control_process, run_control_app
from band_wezterm.wezterm_cli import spawn_first_tab

CONTROL_MODULE: Final = "band_wezterm.tui"


def main() -> int:
    if is_control_process():
        return run_control_app()
    spawned = spawn_first_tab(
        Path.cwd(), [sys.executable, "-m", CONTROL_MODULE]
    )
    print(
        f"Control tab open in window {spawned.window_id.root} "
        f"(pane {spawned.pane_id.root})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
