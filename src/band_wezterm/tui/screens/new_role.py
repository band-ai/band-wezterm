"""Create a new role Markdown file in ~/.band/roles."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label, Static

from band_wezterm.role_library import create_and_open_role
from band_wezterm.roles import role_name_error
from band_wezterm.tui.screens import ControlScreen

PROMPT: Final = "Role name, as it should appear in the picker"


class Id(StrEnum):
    NAME = "new-role-name"
    STATUS = "new-role-status"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


class NewRoleScreen(ControlScreen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("New role")
            yield Static(PROMPT)
            yield Input(placeholder="e.g. Staff Engineer", id=Id.NAME.value)
            yield Static("", id=Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(selector(Id.NAME), Input).focus()

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        error = role_name_error(name)
        if error:
            self.query_one(selector(Id.STATUS), Static).update(error)
            return
        try:
            path = create_and_open_role(name)
        except (OSError, ValueError) as err:
            self.query_one(selector(Id.STATUS), Static).update(str(err))
            return
        self.control.agents_store.status = f"Created role {path.name} — edit and save."
        self.app.pop_screen()
