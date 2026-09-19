"""`band-wezterm` entrypoint — open the band workspace, or be the Control tab."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from band_wezterm.config import CONTROL_TAB_TITLE
from band_wezterm.tui.control_app import is_control_process, run_control_app
from band_wezterm.wezterm_cli import set_tab_title, spawn_first_tab

CONTROL_MODULE: Final = "band_wezterm.tui"


def _control_command() -> list[str]:
    """Spawn via ``env`` so NO_COLOR from the launcher cannot gray out Textual."""
    # macOS ``env`` has no ``--``; name=value then utility.
    return [
        "env",
        "-u",
        "NO_COLOR",
        "COLORTERM=truecolor",
        sys.executable,
        "-m",
        CONTROL_MODULE,
    ]


def main() -> int:
    if is_control_process():
        return run_control_app()
    spawned = spawn_first_tab(Path.cwd(), _control_command())
    set_tab_title(spawned.pane_id, CONTROL_TAB_TITLE)
    print(
        f"Control tab open in window {spawned.window_id.root} "
        f"(pane {spawned.pane_id.root})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
