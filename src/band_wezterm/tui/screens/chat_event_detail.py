"""Chat event detail modal — full content + metadata."""

from __future__ import annotations

from typing import ClassVar, Final

from rich.markdown import Markdown
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from band_wezterm.platform_models import MessageRecord
from band_wezterm.tui.chat_events import (
    content_pretty,
    error_display_content,
    event_tag,
    metadata_pretty,
)

JSON_LEXER: Final = "json"
SYNTAX_THEME: Final = "ansi_dark"
DETAIL_ERROR_STYLE: Final = Style(color="#ff6b80")
DETAIL_MUTED_STYLE: Final = Style(color="#9aa4b2")


def syntax_highlight(content: str) -> Syntax:
    """Render already-normalized structured event data with terminal colors."""
    return Syntax(
        content,
        JSON_LEXER,
        theme=SYNTAX_THEME,
        word_wrap=True,
        background_color="default",
    )


def detail_header(message: MessageRecord, author_color: str | None) -> Text:
    """Build a compact header matching the room timeline's identity styling."""
    header = Text()
    header.append(message.author_name, Style(color=author_color, bold=True))
    header.append("  ")
    header.append_text(event_tag(message.message_type))
    if message.inserted_at is not None:
        header.append("  ")
        header.append(message.inserted_at.astimezone().strftime("%H:%M:%S"), DETAIL_MUTED_STYLE)
    header.append("\n")
    header.append(message.id, DETAIL_MUTED_STYLE)
    return header


def detail_content(message: MessageRecord, content: str) -> str | Text | Markdown | Syntax:
    """Prefer structured rendering, while retaining readable prose and errors."""
    pretty = content_pretty(content)
    if pretty != content:
        return syntax_highlight(pretty)
    if message.message_type == "text":
        return Markdown(content)
    if message.message_type == "error":
        return Text(content, DETAIL_ERROR_STYLE)
    return content


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

    def __init__(self, message: MessageRecord, *, author_color: str | None) -> None:
        super().__init__()
        self._message = message
        self._author_color = author_color

    def compose(self) -> ComposeResult:
        message = self._message
        raw_body = (
            error_display_content(message.content, message.metadata)
            if message.message_type == "error"
            else message.content
        )
        with VerticalScroll() as scroll:
            scroll.border_title = "Event detail"
            yield Static(
                detail_header(message, self._author_color),
                id="detail-header",
                markup=False,
            )
            yield Static(
                detail_content(message, raw_body or "") or "(empty)",
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
