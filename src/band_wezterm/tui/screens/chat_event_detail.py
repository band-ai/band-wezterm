"""Chat event detail modal — full content + metadata."""

from __future__ import annotations

from typing import ClassVar, Final

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from band_wezterm.platform_models import MessageRecord
from band_wezterm.tui.chat_events import (
    badge_label,
    content_pretty,
    error_display_content,
    metadata_pretty,
)

JSON_LEXER: Final = "json"
SYNTAX_THEME: Final = "ansi_dark"


def syntax_highlight(content: str) -> Syntax:
    """Render already-normalized structured event data with terminal colors."""
    return Syntax(
        content,
        JSON_LEXER,
        theme=SYNTAX_THEME,
        word_wrap=True,
        background_color="default",
    )


class ChatEventDetailScreen(ModalScreen[None]):
    """Full payload for one timeline row. Escape dismisses without popping the room."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("q", "dismiss", "Close", show=False),
    ]

    DEFAULT_CSS = """
    ChatEventDetailScreen {
        align: center middle;
    }
    ChatEventDetailScreen > VerticalScroll {
        width: 90%;
        height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1;
    }
    ChatEventDetailScreen #detail-header {
        text-style: bold;
        padding-bottom: 1;
    }
    ChatEventDetailScreen #detail-body {
        height: auto;
        padding-bottom: 1;
    }
    ChatEventDetailScreen #detail-metadata {
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self, message: MessageRecord) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        message = self._message
        header = (
            f"{message.author_name}  "
            f"[{badge_label(message.message_type)}]  {message.id}"
        )
        raw_body = (
            error_display_content(message.content, message.metadata)
            if message.message_type == "error"
            else message.content
        )
        body = content_pretty(raw_body or "")
        with VerticalScroll() as scroll:
            scroll.border_title = "Event detail"
            yield Static(header, id="detail-header", markup=False)
            yield Static(
                syntax_highlight(body) if body != raw_body else body or "(empty)",
                id="detail-body",
                markup=False,
            )
            pretty = metadata_pretty(message.metadata)
            if pretty is not None:
                yield Static("metadata:", markup=False)
                yield Static(
                    syntax_highlight(pretty), id="detail-metadata", markup=False
                )
        yield Footer()
