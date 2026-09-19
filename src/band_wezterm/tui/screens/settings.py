"""Host settings — rooms/chat limits and diagnostic toggles (VSC settings parity)."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label, Static, Switch

from band_wezterm.preferences import (
    MAX_CHAT_MESSAGES_LIMIT,
    MAX_ROOMS_PAGE_SIZE,
    MIN_CHAT_MESSAGES_LIMIT,
    MIN_ROOMS_PAGE_SIZE,
)
from band_wezterm.tui.screens import ControlScreen

SAVE_HINT: Final = "Enter on a field saves it. Esc returns. Ctrl+L signs out."


class Id(StrEnum):
    ROOMS = "settings-rooms-page"
    CHAT = "settings-chat-limit"
    DIAG = "settings-diag"
    VERBOSE = "settings-verbose"
    STATUS = "settings-status"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


class SettingsScreen(ControlScreen):
    """Local Control preferences — persisted under ~/.band-wezterm/."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back", show=False),
        Binding("ctrl+a", "app.show_agents", "Agents", show=False),
        Binding("ctrl+o", "app.show_rooms", "Rooms", show=False),
        Binding("ctrl+l", "sign_out", "Sign out"),
    ]

    DEFAULT_CSS = """
    SettingsScreen Input {
        margin: 0 1 1 1;
    }
    SettingsScreen .row {
        height: 3;
        padding: 0 1;
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
            yield Label("Rooms page size")
            yield Input(
                value=str(prefs.rooms_page_size),
                id=Id.ROOMS.value,
                type="integer",
            )
            yield Label("Chat messages limit")
            yield Input(
                value=str(prefs.chat_messages_limit),
                id=Id.CHAT.value,
                type="integer",
            )
            with Vertical(classes="row"):
                yield Label("Diagnostic log")
                yield Switch(value=prefs.diagnostic_log, id=Id.DIAG.value)
            with Vertical(classes="row"):
                yield Label("Verbose diagnostic log")
                yield Switch(value=prefs.diagnostic_log_verbose, id=Id.VERBOSE.value)
            yield Static("", id=Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(selector(Id.ROOMS), Input).focus()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_sign_out(self) -> None:
        self.app.pop_screen()
        self.control.action_sign_out()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save_numbers()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        match event.switch.id:
            case Id.DIAG:
                self.control.preferences.update(diagnostic_log=event.value)
            case Id.VERBOSE:
                self.control.preferences.update(diagnostic_log_verbose=event.value)
        self._set_status("Saved.")

    def _save_numbers(self) -> None:
        rooms_raw = self.query_one(selector(Id.ROOMS), Input).value.strip()
        chat_raw = self.query_one(selector(Id.CHAT), Input).value.strip()
        try:
            rooms = int(rooms_raw)
            chat = int(chat_raw)
        except ValueError:
            self._set_status("Rooms page size and chat limit must be integers.")
            return
        if not MIN_ROOMS_PAGE_SIZE <= rooms <= MAX_ROOMS_PAGE_SIZE:
            self._set_status(
                f"Rooms page size must be {MIN_ROOMS_PAGE_SIZE}-{MAX_ROOMS_PAGE_SIZE}."
            )
            return
        if not MIN_CHAT_MESSAGES_LIMIT <= chat <= MAX_CHAT_MESSAGES_LIMIT:
            self._set_status(
                f"Chat limit must be {MIN_CHAT_MESSAGES_LIMIT}-{MAX_CHAT_MESSAGES_LIMIT}."
            )
            return
        self.control.preferences.update(
            rooms_page_size=rooms, chat_messages_limit=chat
        )
        self._set_status("Saved.")

    def _set_status(self, status: str) -> None:
        self.query_one(selector(Id.STATUS), Static).update(status)
