"""Generic yes/no confirmation modal — this app's first confirmation prompt."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmScreen(ModalScreen[bool]):
    """Ask one yes/no question; dismiss(True) on confirm, dismiss(False) otherwise."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "decline", "No", show=True),
        Binding("n", "decline", "No", show=False),
        Binding("y", "confirm", "Yes", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Vertical {
        width: 60;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1;
    }
    ConfirmScreen #confirm-message {
        padding-bottom: 1;
    }
    ConfirmScreen Horizontal {
        height: auto;
        align: right middle;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._message, id="confirm-message")
            with Horizontal():
                yield Button("No", id="confirm-no")
                yield Button("Yes", id="confirm-yes", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_decline(self) -> None:
        self.dismiss(False)
