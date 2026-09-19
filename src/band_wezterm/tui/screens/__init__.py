"""Control tab screens.

Screens only ever reach the platform through ``BandClient`` and the terminal
through ``wezterm_cli``/``osc`` — never through ``band_rest`` or a shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.screen import Screen

if TYPE_CHECKING:
    from band_wezterm.tui.control_app import ControlApp


class ControlScreen(Screen[None]):
    """Base screen giving every screen typed access to the host app."""

    @property
    def control(self) -> ControlApp:
        return cast("ControlApp", self.app)
