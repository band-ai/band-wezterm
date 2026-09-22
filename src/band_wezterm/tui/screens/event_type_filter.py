"""Event-type filter overlay — multi-select categories with counts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, ListItem, ListView, Static

from band_wezterm.platform_models import MessageRecord
from band_wezterm.tui.chat_events import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    EventFilterCategory,
    all_categories_selected,
    category_selected,
    clear_all_categories,
    count_by_category,
    select_all_categories,
    toggle_category,
)


class EventTypeFilterScreen(ModalScreen[None]):
    """Checkbox-style category picker. Escape dismisses without discarding live edits."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss", "Close", show=True),
        Binding("q", "dismiss", "Close", show=False),
        Binding("enter", "toggle", "Toggle", show=True),
        Binding("space", "toggle", "Toggle", show=False),
    ]

    DEFAULT_CSS = """
    EventTypeFilterScreen {
        align: center middle;
    }
    EventTypeFilterScreen > Vertical {
        width: 44;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1;
    }
    EventTypeFilterScreen #event-filter-title {
        text-style: bold;
        padding-bottom: 1;
    }
    EventTypeFilterScreen ListView {
        height: auto;
        max-height: 20;
    }
    EventTypeFilterScreen ListItem {
        height: 1;
    }
    """

    class Changed(Message):
        def __init__(self, allowed: tuple[str, ...]) -> None:
            super().__init__()
            self.allowed = allowed

    def __init__(
        self,
        allowed: Sequence[str],
        messages: Sequence[MessageRecord],
    ) -> None:
        super().__init__()
        self._allowed = tuple(allowed)
        self._messages = list(messages)
        self._counts = count_by_category(self._messages)
        self._cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Event types", id="event-filter-title")
            yield ListView(id="event-filter-list")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._rebuild_list(), exclusive=True, group="event-filter")

    async def _rebuild_list(self) -> None:
        list_view = self.query_one("#event-filter-list", ListView)
        select_all_mark = "x" if all_categories_selected(self._allowed) else " "
        total = sum(self._counts.values())
        rows: list[ListItem] = [
            ListItem(
                Label(f"[{select_all_mark}] Select all ({total})", markup=False),
                id="filter-select-all",
            )
        ]
        for category in CATEGORY_ORDER:
            mark = "x" if category_selected(category, self._allowed) else " "
            label = CATEGORY_LABELS[category]
            count = self._counts[category]
            rows.append(
                ListItem(
                    Label(f"[{mark}] {label} ({count})", markup=False),
                    id=f"filter-{category.value}",
                )
            )
        await list_view.clear()
        await list_view.extend(rows)
        if rows:
            list_view.index = min(self._cursor, len(rows) - 1)
        list_view.focus()

    def _selected_category(self) -> EventFilterCategory | None:
        list_view = self.query_one("#event-filter-list", ListView)
        item = list_view.highlighted_child
        if item is None or item.id is None:
            return None
        if item.id == "filter-select-all":
            return None
        key = item.id.removeprefix("filter-")
        try:
            return EventFilterCategory(key)
        except ValueError:
            return None

    def _is_select_all_row(self) -> bool:
        item = self.query_one("#event-filter-list", ListView).highlighted_child
        return item is not None and item.id == "filter-select-all"

    def action_toggle(self) -> None:
        list_view = self.query_one("#event-filter-list", ListView)
        self._cursor = list_view.index or 0
        if self._is_select_all_row():
            if all_categories_selected(self._allowed):
                self._allowed = clear_all_categories(self._allowed)
            else:
                self._allowed = select_all_categories(self._allowed)
        else:
            category = self._selected_category()
            if category is None:
                return
            self._allowed = toggle_category(category, self._allowed)
        self.post_message(self.Changed(self._allowed))
        self.run_worker(self._rebuild_list(), exclusive=True, group="event-filter")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        self.action_toggle()
