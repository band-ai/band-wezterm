"""Host settings that change an active Band view."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static, Switch

from band_wezterm.diagnostics import diagnostics_log_path
from band_wezterm.pane_identity import announce_control_preferences
from band_wezterm.preferences import MAX_CHAT_MESSAGES_LIMIT, MIN_CHAT_MESSAGES_LIMIT
from band_wezterm.tui.screens import ControlScreen

SAVE_HINT: Final = "Changes save when you press Enter. Esc returns to Band."
HISTORY_DESCRIPTION: Final = "Messages loaded each time you reach the beginning of a room."
BACKGROUND_DESCRIPTION: Final = "Apply the subtle Band background to this WezTerm window."
PLATFORM_DESCRIPTION: Final = "Set BAND_DEPLOYMENT=development before launching Band to use dev."
LOG_FILE_DESCRIPTION: Final = "Use `band logs --tail 100` for incident triage."
ACCOUNT_LABEL: Final = "Account · signing out stops local workers"
HISTORY_LABEL: Final = "Room history · page size"
BACKGROUND_LABEL: Final = "Appearance · show Band background"


class Id(StrEnum):
    CONTENT = "settings-content"
    CHAT = "settings-chat-limit"
    LOG_FILE = "settings-log-file"
    STATUS = "settings-status"
    SIGN_OUT = "settings-sign-out"
    BACKGROUND = "settings-background"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


class SettingsScreen(ControlScreen):
    """Local Band preferences — persisted under ~/.band-wezterm/."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back", show=False),
    ]

    DEFAULT_CSS = """
    SettingsScreen {
        align: center top;
    }

    SettingsScreen #settings-content {
        width: 1fr;
        max-width: 88;
        padding: 1 2 2 2;
    }

    SettingsScreen .settings-title {
        color: $accent;
        text-style: bold;
    }

    SettingsScreen .settings-summary,
    SettingsScreen .setting-description,
    SettingsScreen .setting-value {
        color: $text-muted;
    }

    SettingsScreen .settings-summary {
        margin-bottom: 1;
    }

    SettingsScreen .settings-section {
        height: auto;
        margin-bottom: 0;
    }

    SettingsScreen .danger-section {
        background: $error 10%;
    }

    SettingsScreen .settings-section-title {
        color: $accent;
        text-style: bold;
        background: $panel;
        padding: 0 1;
    }

    SettingsScreen .setting-row {
        height: auto;
        padding: 0 1;
    }

    SettingsScreen .setting-copy {
        width: 1fr;
        height: auto;
    }

    SettingsScreen .setting-label {
        text-style: bold;
    }

    SettingsScreen .setting-description {
        height: auto;
    }

    SettingsScreen .setting-input {
        width: 8;
        margin: 0 0 0 2;
    }

    SettingsScreen .setting-switch {
        width: auto;
        margin: 0 0 0 2;
    }

    SettingsScreen #settings-status {
        height: 1;
        color: $success;
        margin: 0 1;
    }

    SettingsScreen .danger-action {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        prefs = self.control.preferences.current
        yield Header()
        with Vertical(id=Id.CONTENT.value):
            yield Label("Settings", classes="settings-title")
            yield Static(SAVE_HINT, classes="settings-summary")
            with Vertical(classes="settings-section"):
                yield Label("Platform", classes="settings-section-title")
                deployment = self.control.settings.band_deployment.value
                yield Static(
                    f"{deployment.title()} · {self.control.settings.band_base_url}",
                    classes="setting-value",
                )
                yield Static(PLATFORM_DESCRIPTION, classes="setting-description")

            with Vertical(classes="settings-section"), Horizontal(
                classes="setting-row"
            ):
                with Vertical(classes="setting-copy"):
                    yield Label(HISTORY_LABEL, classes="setting-label")
                    yield Static(HISTORY_DESCRIPTION, classes="setting-description")
                yield Input(
                    value=str(prefs.chat_messages_limit),
                    id=Id.CHAT.value,
                    type="integer",
                    classes="setting-input",
                )

            with Vertical(classes="settings-section"), Horizontal(
                classes="setting-row"
            ):
                with Vertical(classes="setting-copy"):
                    yield Label(BACKGROUND_LABEL, classes="setting-label")
                    yield Static(BACKGROUND_DESCRIPTION, classes="setting-description")
                yield Switch(
                    prefs.show_band_background,
                    id=Id.BACKGROUND.value,
                    classes="setting-switch",
                )

            with Vertical(classes="settings-section"):
                yield Label("Diagnostics", classes="settings-section-title")
                yield Label("Log file", classes="setting-label")
                yield Static(
                    str(diagnostics_log_path(settings=self.control.settings)),
                    id=Id.LOG_FILE.value,
                    classes="setting-value",
                )
                yield Static(LOG_FILE_DESCRIPTION, classes="setting-description")

            yield Static("", id=Id.STATUS.value)
            with Vertical(classes="settings-section danger-section"):
                yield Label(ACCOUNT_LABEL, classes="settings-section-title")
                yield Button(
                    "Sign out",
                    id=Id.SIGN_OUT.value,
                    variant="error",
                    classes="danger-action",
                    compact=True,
                )
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

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != Id.BACKGROUND:
            return
        self.control.preferences.update(show_band_background=event.value)
        announce_control_preferences(show_band_background=event.value)
        self._set_status("Saved.")

    def _save_numbers(self) -> None:
        chat_raw = self.query_one(selector(Id.CHAT), Input).value.strip()
        try:
            chat = int(chat_raw)
        except ValueError:
            self._set_status("Chat history page size must be an integer.")
            return
        if not MIN_CHAT_MESSAGES_LIMIT <= chat <= MAX_CHAT_MESSAGES_LIMIT:
            self._set_status(
                "Chat history page size must be "
                f"{MIN_CHAT_MESSAGES_LIMIT}-{MAX_CHAT_MESSAGES_LIMIT}."
            )
            return
        self.control.preferences.update(chat_messages_limit=chat)
        self._set_status("Saved.")

    def _set_status(self, status: str) -> None:
        self.query_one(selector(Id.STATUS), Static).update(status)
