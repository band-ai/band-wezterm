"""Reusable Control tab widgets: avatars, markdown composer, filter chips."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final, Protocol, runtime_checkable

from rich.highlighter import Highlighter
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.suggester import Suggester
from textual.widget import Widget
from textual.widgets import Input, Static

from band_wezterm.identity import AvatarKind, initials

AVATAR_CELLS: Final = 2
AVATAR_FRAMES: Final[dict[AvatarKind, tuple[str, str]]] = {
    AvatarKind.AGENT: ("[", "]"),
    AvatarKind.HUMAN: ("(", ")"),
}
LUMINANCE_WEIGHTS: Final[tuple[float, float, float]] = (0.2126, 0.7152, 0.0722)
LUMINANCE_PIVOT: Final = 0.55
DARK_INK: Final = "#000000"
LIGHT_INK: Final = "#ffffff"

BOLD_SPAN: Final = re.compile(r"\*\*(?=\S)(?:[^*]|\*(?!\*))+\*\*")
CODE_SPAN: Final = re.compile(r"`[^`\n]+`")
MENTION_SPAN: Final = re.compile(r"(?:(?<=\s)|\A)@[^\s@]+")
MENTION_QUERY: Final = re.compile(r"(?:(?<=\s)|\A)@(?P<query>[^\s@\[\]]*)$")

COMPOSER_SPANS: Final[tuple[tuple[re.Pattern[str], Style], ...]] = (
    (BOLD_SPAN, Style(bold=True)),
    (CODE_SPAN, Style(color="#a5d6ff", bgcolor="#30363d")),
    (MENTION_SPAN, Style(color="#7ee787", bold=True)),
)

CHIP_ON: Final = Style(color=DARK_INK, bgcolor="#7ee787", bold=True)
CHIP_OFF: Final = Style(color="#9aa4b2")
CHIP_CURSOR: Final = Style(underline=True)
CHIP_SEPARATOR: Final = " "


@runtime_checkable
class Identity(Protocol):
    """Anything that renders as an avatar (agents, participants)."""

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> AvatarKind: ...

    @property
    def color(self) -> str: ...


def readable_ink(hex_color: str) -> str:
    """Pick black/white text so initials stay legible on any accent."""
    raw = hex_color.lstrip("#")
    channels = (int(raw[index : index + 2], 16) / 255.0 for index in (0, 2, 4))
    luminance = sum(
        weight * channel
        for weight, channel in zip(LUMINANCE_WEIGHTS, channels, strict=True)
    )
    return DARK_INK if luminance > LUMINANCE_PIVOT else LIGHT_INK


def avatar_text(identity: Identity) -> Text:
    """Two coloured cells of initials, square-framed for agents, round for humans."""
    frame_left, frame_right = AVATAR_FRAMES[identity.kind]
    label = initials(identity.name).ljust(AVATAR_CELLS)[:AVATAR_CELLS]
    text = Text()
    text.append(frame_left, Style(color=identity.color))
    text.append(
        label,
        Style(color=readable_ink(identity.color), bgcolor=identity.color, bold=True),
    )
    text.append(frame_right, Style(color=identity.color))
    return text


class AvatarChip(Static):
    """Identity avatar: colored block + initials."""

    DEFAULT_CSS = """
    AvatarChip {
        width: 4;
        height: 1;
        margin-right: 1;
    }
    """

    def __init__(self, identity: Identity, *, classes: str | None = None) -> None:
        super().__init__(avatar_text(identity), classes=classes)
        self._identity = identity

    def set_identity(self, identity: Identity) -> None:
        self._identity = identity
        self.update(avatar_text(identity))


class MarkdownSpanHighlighter(Highlighter):
    """Live inline markdown + mention highlighting for the composer (W3)."""

    def highlight(self, text: Text) -> None:
        plain = text.plain
        for pattern, style in COMPOSER_SPANS:
            for match in pattern.finditer(plain):
                text.stylize(style, *match.span())


def mention_token(handle: str) -> str:
    """Render a handle as it appears in the composer."""
    return f"@{handle}"


class MentionSuggester(Suggester):
    """Complete the final `@` query from the current room's handles."""

    def __init__(self, handles: Callable[[], Iterable[str]]) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._handles = handles

    async def get_suggestion(self, value: str) -> str | None:
        match = MENTION_QUERY.search(value)
        if match is None:
            return None
        query = match.group("query")
        handle = next(
            (
                candidate
                for candidate in self._handles()
                if candidate.casefold().startswith(query)
            ),
            None,
        )
        if handle is None:
            return None
        return f"{value[: match.start()]}{mention_token(handle)} "


class MarkdownComposer(Input):
    """Single-line composer highlighting `**bold**`, `` `code` `` and `@mention`."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("tab", "complete_mention", "Complete handle", show=False),
    ]

    def __init__(
        self,
        *,
        placeholder: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._mention_handles: tuple[str, ...] = ()
        super().__init__(
            placeholder=placeholder,
            highlighter=MarkdownSpanHighlighter(),
            suggester=MentionSuggester(lambda: self._mention_handles),
            id=id,
            classes=classes,
        )

    def set_mention_handles(self, handles: Iterable[str]) -> None:
        self._mention_handles = tuple(handles)

    def action_complete_mention(self) -> None:
        """Accept the inline handle completion when the cursor is at the end."""
        if self.cursor_at_end:
            self.action_cursor_right()


@dataclass(frozen=True)
class Chip:
    key: str
    label: str


class FilterChips(Widget):
    """Chip row for catalog filters.

    Default is multi-select (AND). Pass ``exclusive=True`` for radio behaviour
    (exactly one chip selected — used by the Agents screen with an All chip).
    """

    DEFAULT_CSS = """
    FilterChips {
        height: 1;
        width: 1fr;
    }
    FilterChips:focus {
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("left", "move(-1)", "Prev chip", show=False),
        Binding("right", "move(1)", "Next chip", show=False),
        Binding("space", "toggle", "Toggle chip", show=False),
        Binding("enter", "toggle", "Toggle chip", show=False),
    ]

    can_focus = True

    cursor: reactive[int] = reactive(0)
    selected: reactive[frozenset[str]] = reactive(frozenset)

    class Changed(Message):
        """Posted whenever the selected chip set changes."""

        def __init__(self, chips: FilterChips, selected: frozenset[str]) -> None:
            super().__init__()
            self.chips = chips
            self.selected = selected

        @property
        def control(self) -> FilterChips:
            return self.chips

    def __init__(
        self,
        chips: Sequence[Chip],
        *,
        exclusive: bool = False,
        selected: frozenset[str] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._chips = tuple(chips)
        self._exclusive = exclusive
        if selected is not None:
            self.selected = frozenset(selected)

    def render(self) -> Text:
        text = Text()
        for index, chip in enumerate(self._chips):
            style = CHIP_ON if chip.key in self.selected else CHIP_OFF
            if self.has_focus and index == self.cursor:
                style += CHIP_CURSOR
            text.append(f" {chip.label} ", style)
            text.append(CHIP_SEPARATOR)
        return text

    def watch_cursor(self) -> None:
        self.refresh()

    def watch_selected(self) -> None:
        self.refresh()

    def action_move(self, delta: int) -> None:
        if not self._chips:
            return
        self.cursor = (self.cursor + delta) % len(self._chips)

    def action_toggle(self) -> None:
        if not self._chips:
            return
        key = self._chips[self.cursor].key
        if self._exclusive:
            if self.selected == frozenset({key}):
                return
            self.selected = frozenset({key})
        else:
            self.selected = self.selected ^ {key}
        self.post_message(self.Changed(self, self.selected))
