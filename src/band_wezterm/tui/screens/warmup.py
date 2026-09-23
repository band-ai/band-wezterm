"""Readiness gate shown while a Band surface acquires shared local runtime state."""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle
from textual.widgets import Footer, Header, ProgressBar, Static

from band_wezterm.tui.screens import ControlScreen

WARMUP_TOTAL_STEPS: Final = 3
WARMUP_TITLE: Final = "Preparing Band"
WARMUP_INITIAL_MESSAGE: Final = "Connecting to Band…"
WARMUP_RETRY_HINT: Final = "Press Enter to retry."


class WarmupScreen(ControlScreen):
    """Disable interaction until this tab has a ready platform and supervisor."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("enter", "retry", "Retry")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle():
            with Center():
                yield Static(WARMUP_TITLE, id="warmup-title")
            with Center():
                yield ProgressBar(total=WARMUP_TOTAL_STEPS, id="warmup-progress")
            with Center():
                yield Static(WARMUP_INITIAL_MESSAGE, id="warmup-status")
        yield Footer()

    def set_progress(self, step: int, message: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#warmup-progress", ProgressBar).update(progress=step)
        self.query_one("#warmup-status", Static).update(message)

    def show_retry(self, message: str) -> None:
        self.set_progress(0, f"{message}\n\n{WARMUP_RETRY_HINT}")

    def action_retry(self) -> None:
        self.control.start_warmup()
