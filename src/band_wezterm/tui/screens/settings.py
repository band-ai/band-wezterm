"""Host settings that change an active Band view."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static

from band_wezterm.diagnostics import diagnostics_log_path
from band_wezterm.preferences import MAX_CHAT_MESSAGES_LIMIT, MIN_CHAT_MESSAGES_LIMIT
from band_wezterm.tui.screens import ControlScreen

SAVE_HINT: Final = "Enter on a field saves it. Esc returns."


class Id(StrEnum):
    CHAT = "settings-chat-limit"
    LOG_FILE = "settings-log-file"
    STATUS = "settings-status"
    SIGN_OUT = "settings-sign-out"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


class SettingsScreen(ControlScreen):
    """Local Band preferences — persisted under ~/.band-wezterm/."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back", show=False),
    ]

    DEFAULT_CSS = """
    SettingsScreen Input {
        margin: 0 1 1 1;
    }
    SettingsScreen #settings-status {
        height: 1;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        prefs = self.control.preferences.current
        yield Header()
        with Vertical():
            yield Label("Settings")
            yield Static(SAVE_HINT)
            yield Label("Platform")
            deployment = self.control.settings.band_deployment.value
            yield Static(
                f"{deployment.title()} ({self.control.settings.band_base_url})\n"
                "Set BAND_DEPLOYMENT=development before launching Band to use dev."
            )
            yield Label("Chat messages limit")
            yield Input(
                value=str(prefs.chat_messages_limit),
                id=Id.CHAT.value,
                type="integer",
            )
            yield Label("Log file")
            yield Static(
                str(diagnostics_log_path(settings=self.control.settings)),
                id=Id.LOG_FILE.value,
            )
            yield Static("Use `band logs --tail 100` for incident triage.")
            yield Static("", id=Id.STATUS.value)
            yield Button("Sign out", id=Id.SIGN_OUT.value)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(selector(Id.CHAT), Input).focus()

    def action_back(self) -> None:
        self.app.pop_screen()

    def _sign_out(self) -> None:
        self.app.pop_screen()
        self.control.action_sign_out()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save_numbers()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case Id.SIGN_OUT:
                self._sign_out()

    def _save_numbers(self) -> None:
        chat_raw = self.query_one(selector(Id.CHAT), Input).value.strip()
        try:
            chat = int(chat_raw)
        except ValueError:
            self._set_status("Chat limit must be an integer.")
            return
        if not MIN_CHAT_MESSAGES_LIMIT <= chat <= MAX_CHAT_MESSAGES_LIMIT:
            self._set_status(
                f"Chat limit must be {MIN_CHAT_MESSAGES_LIMIT}-{MAX_CHAT_MESSAGES_LIMIT}."
            )
            return
        self.control.preferences.update(chat_messages_limit=chat)
        self._set_status("Saved.")

    def _set_status(self, status: str) -> None:
        self.query_one(selector(Id.STATUS), Static).update(status)
