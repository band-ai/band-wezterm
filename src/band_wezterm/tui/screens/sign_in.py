"""First-run sign-in — the only screen shown before tokens exist."""

from __future__ import annotations

from typing import ClassVar, Final

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

from band_wezterm.errors import format_platform_error
from band_wezterm.tui.screens import ControlScreen

SIGN_IN_TITLE: Final = "Band"
SIGN_IN_PROMPT: Final = "Press Enter to sign in"
SIGN_IN_PENDING: Final = "Waiting for the browser to complete sign-in…"
SIGN_IN_HINT: Final = (
    "Sign-in opens your browser. Press Esc to cancel and try again."
)


class SignInScreen(ControlScreen):
    """Blocking gate: no platform call happens until sign-in succeeds."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "sign_in", "Sign in"),
        Binding("escape", "cancel_sign_in", "Cancel", show=False),
        Binding("ctrl+q", "quit_host", "Quit host"),
    ]

    status: reactive[str] = reactive(SIGN_IN_PROMPT)
    busy: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle():
            with Center():
                yield Static(SIGN_IN_TITLE, id="sign-in-title")
            with Center():
                yield Static(self.status, id="sign-in-status")
            with Center():
                yield Static(SIGN_IN_HINT, id="sign-in-hint")
        yield Footer()

    def watch_status(self, status: str) -> None:
        if self.is_mounted:
            self.query_one("#sign-in-status", Static).update(status)

    def action_sign_in(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.status = SIGN_IN_PENDING
        self._sign_in()

    def action_quit_host(self) -> None:
        self.control.exit()

    def action_cancel_sign_in(self) -> None:
        if self.busy:
            self.control.host_auth.cancel_sign_in()

    @work(exclusive=True)
    async def _sign_in(self) -> None:
        try:
            if not self.control.host_auth.has_stored_tokens():
                await self.control.host_auth.sign_in()
            await self.control.enter_workspace()
        except Exception as error:  # surfaced in-screen; retry with Enter
            message = format_platform_error(error, operation="sign in")
            self.status = f"{message}\n\n{SIGN_IN_PROMPT}"
        finally:
            self.busy = False
