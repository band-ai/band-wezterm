"""Rooms — list, starring, creation, roster management and chat."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import ClassVar, Final

from rich.markdown import Markdown
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from band_wezterm.client import (
    AgentRecord,
    MessageRecord,
    ParticipantRecord,
    RealtimeEvent,
    RealtimeEventKind,
    RoomRecord,
    Unsubscribe,
    display_message_content,
)
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import AgentRuntime, AvatarKind
from band_wezterm.platform_models import DEFAULT_MESSAGE_TYPE
from band_wezterm.tui.catalog_loaders import list_rooms
from band_wezterm.tui.chat_events import (
    DISCLOSURE_COLLAPSED,
    DISCLOSURE_EXPANDED,
    FILTERED_EMPTY_CHAT,
    apply_verbose,
    badge_label,
    error_display_content,
    event_tag_class,
    hidden_summary,
    is_always_expanded,
    metadata_pretty,
    timeline_content,
    timeline_preview,
    verbose_active,
    visible_messages,
)
from band_wezterm.tui.managed_agent_actions import ManagedAgentActions
from band_wezterm.tui.refresh import install_catalog_refresh
from band_wezterm.tui.roster_order import order_roster
from band_wezterm.tui.screens import ControlScreen
from band_wezterm.tui.screens.chat_event_detail import ChatEventDetailScreen
from band_wezterm.tui.screens.event_type_filter import EventTypeFilterScreen
from band_wezterm.tui.stores import (
    ROOM_FILTER_LABELS,
    RoomFilter,
    RoomsStore,
    RoomStatusSource,
)
from band_wezterm.tui.widgets import (
    AvatarChip,
    Chip,
    FilterChips,
    Identity,
    MarkdownComposer,
)

ROOM_DOT: Final = "●"
RUNTIME_DOT: Final = "●"
RUNNING_DOT_COLOR: Final = "#7ee787"
STOPPED_DOT_COLOR: Final = "#6e7681"
STAR_ON: Final = "★"
STAR_OFF: Final = "☆"
OPEN_CLASS: Final = "open"

SEARCH_PLACEHOLDER: Final = "Filter rooms"
DRAFT_TITLE: Final = "New room — Enter creates it and opens the room"
DRAFT_PLACEHOLDER: Final = "Room title"
COMPOSER_PLACEHOLDER: Final = "@mention a participant, **bold**, `code`"
PICKER_TITLE: Final = "Add participant — Enter adds the highlighted agent"
ROSTER_TITLE: Final = "Roster"
EMPTY_ROOMS: Final = "No rooms match the filter."
EMPTY_CHAT: Final = "*No messages yet.*"
NEW_ACTIVITY_MESSAGE: Final = "New activity — End jumps to latest."
MESSAGE_TIME_FORMAT: Final = "%H:%M:%S"
EMPTY_CANDIDATES: Final = "Every one of your agents is already in this room."
ROSTER_UPDATING_MESSAGE: Final = "Updating room roster…"
NO_SELECTION_MESSAGE: Final = "Select a room first."
NO_PARTICIPANT_MESSAGE: Final = "Select a participant first."
NO_AGENT_PARTICIPANT_MESSAGE: Final = "Select an agent participant first."
MENTION_REQUIRED_MESSAGE: Final = "Messages must @mention a room participant."
EMPTY_TITLE_MESSAGE: Final = "A room title is required."
DELETE_CONFIRM_MESSAGE: Final = "Press Delete again to permanently remove {title}."

ROOM_CHIPS: Final[tuple[Chip, ...]] = tuple(
    Chip(key=chip.value, label=label) for chip, label in ROOM_FILTER_LABELS.items()
)


class Id(StrEnum):
    """Widget ids owned by the rooms screens."""

    SEARCH = "room-search"
    FILTERS = "room-filters"
    LIST = "room-list"
    DRAFT = "room-draft"
    DRAFT_TITLE = "room-draft-title"
    STATUS = "room-status"
    TOOLBAR = "room-toolbar"
    HEADING = "room-heading"
    ROSTER = "room-roster"
    PICKER = "room-picker"
    PICKER_LIST = "room-picker-list"
    CHAT = "room-chat"
    CHAT_SCROLL = "room-chat-scroll"
    CHAT_HIDDEN = "room-chat-hidden"
    COMPOSER = "room-composer"
    DETAIL_STATUS = "room-detail-status"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


def mention_keys(participant: ParticipantRecord) -> tuple[str, ...]:
    """Accepted composer keys, preferring the platform's canonical handle."""
    keys = (participant.handle, participant.name)
    return tuple(dict.fromkeys(key for key in keys if key))


def resolve_mentions(
    body: str, participants: Iterable[ParticipantRecord]
) -> tuple[list[ParticipantRecord], str] | None:
    """Every distinct `@handle` left-to-right, plus the body with those tokens removed.

    Longer keys win at the same offset (so ``@Developer 6753`` beats ``@Developer``);
    canonical handles beat name aliases of equal length.
    """
    candidates = sorted(
        (
            (key, participant, key == participant.handle)
            for participant in participants
            for key in mention_keys(participant)
        ),
        key=lambda candidate: (len(candidate[0]), candidate[2]),
        reverse=True,
    )
    found: list[ParticipantRecord] = []
    seen_ids: set[str] = set()
    remaining = body
    while True:
        best: tuple[int, int, ParticipantRecord] | None = None
        for key, participant, _is_handle in candidates:
            match = re.search(
                rf"(?<!\S)@{re.escape(key)}(?=\s|$)", remaining, flags=re.IGNORECASE
            )
            if match is None:
                continue
            start, end = match.start(), match.end()
            if best is None or start < best[0] or (start == best[0] and end > best[1]):
                best = (start, end, participant)
        if best is None:
            break
        start, end, participant = best
        if participant.id not in seen_ids:
            found.append(participant)
            seen_ids.add(participant.id)
        remaining = re.sub(
            r" {2,}", " ", f"{remaining[:start]}{remaining[end:]}".strip()
        )
    if not found:
        return None
    return found, remaining


def resolve_mention(
    body: str, participants: Iterable[ParticipantRecord]
) -> tuple[ParticipantRecord, str] | None:
    """First of :func:`resolve_mentions` — kept for single-recipient call sites."""
    resolved = resolve_mentions(body, participants)
    if resolved is None:
        return None
    mentioned, remainder = resolved
    return mentioned[0], remainder


async def refill(list_view: ListView, rows: Sequence[ListItem]) -> None:
    """Replace every row, keeping the highlight on a still-valid index."""
    previous = list_view.index
    await list_view.clear()
    await list_view.extend(rows)
    list_view.index = min(previous or 0, len(rows) - 1) if rows else None


_MESSAGE_EVENT_KINDS = frozenset(
    {
        RealtimeEventKind.MESSAGE,
        RealtimeEventKind.MESSAGE_CREATED,
        RealtimeEventKind.MESSAGE_UPDATED,
        RealtimeEventKind.EVENT_CREATED,
    }
)
_ROSTER_EVENT_KINDS = frozenset(
    {RealtimeEventKind.PARTICIPANT_JOINED, RealtimeEventKind.PARTICIPANT_LEFT}
)


def message_from_event(event: RealtimeEvent) -> MessageRecord | None:
    if event.kind not in _MESSAGE_EVENT_KINDS:
        return None
    payload = event.payload or {}
    if "content" in payload:
        content = payload.get("content")
    elif "body" in payload:
        content = payload.get("body")
    else:
        content = None
    if content is None:
        return None
    metadata = payload.get("metadata")
    meta = metadata if isinstance(metadata, dict) else None
    raw_type = payload.get("message_type")
    return MessageRecord(
        id=str(payload.get("id") or event.kind.value),
        content=display_message_content(str(content), meta),
        author_name=str(
            payload.get("sender_name")
            or payload.get("author_name")
            or payload.get("sender")
            or "unknown"
        ),
        author_id=(
            str(sender_id)
            if (sender_id := payload.get("sender_id") or payload.get("senderId"))
            else None
        ),
        inserted_at=payload.get("inserted_at") or payload.get("insertedAt"),
        message_type=str(raw_type or DEFAULT_MESSAGE_TYPE),
        metadata=meta,
    )


def message_time_label(message: MessageRecord) -> str:
    """Render a compact local time when the platform supplied one."""
    inserted_at = message.inserted_at
    return (
        ""
        if inserted_at is None
        else inserted_at.astimezone().strftime(MESSAGE_TIME_FORMAT)
    )


class ChatEventRow(ListItem):
    """One timeline event: author, badge, body or collapsed preview."""

    DEFAULT_CSS = """
    ChatEventRow {
        height: auto;
        padding: 0 1;
        border-bottom: solid $panel;
    }
    ChatEventRow .event-header {
        height: 1;
    }
    ChatEventRow .event-author {
        text-style: bold;
        width: 1fr;
    }
    ChatEventRow .event-meta {
        width: auto;
    }
    ChatEventRow .event-timestamp {
        color: $text-muted;
        margin-left: 1;
        width: auto;
    }
    ChatEventRow .event-tag {
        padding: 0 1;
        text-style: bold;
        width: auto;
    }
    ChatEventRow .event-tag-text { background: $accent; color: $text; }
    ChatEventRow .event-tag-thought { background: $primary; color: $text; }
    ChatEventRow .event-tag-task { background: $warning; color: $text; }
    ChatEventRow .event-tag-tool-call { background: $secondary; color: $text; }
    ChatEventRow .event-tag-tool-result { background: $success; color: $text; }
    ChatEventRow .event-tag-error { background: $error; color: $text; }
    ChatEventRow .event-tag-attention { background: $warning; color: $text; }
    ChatEventRow .event-tag-system { background: $surface-lighten-1; color: $text-muted; }
    ChatEventRow .event-badge {
        color: $accent;
    }
    ChatEventRow .event-preview {
        color: $text-muted;
    }
    ChatEventRow .event-body {
        height: auto;
    }
    """

    def __init__(
        self,
        message: MessageRecord,
        *,
        expanded: bool,
        author_color: str | None,
    ) -> None:
        super().__init__()
        self.message = message
        self.expanded = expanded
        self.author_color = author_color

    def compose(self) -> ComposeResult:
        message = self.message
        message_type = message.message_type or DEFAULT_MESSAGE_TYPE
        with Horizontal(classes="event-header"):
            author = Text(message.author_name, Style(color=self.author_color, bold=True))
            yield Static(author, classes="event-author", markup=False)
            with Horizontal(classes="event-meta"):
                yield Static(
                    badge_label(message_type),
                    classes=f"event-tag {event_tag_class(message_type)}",
                    markup=False,
                )
                timestamp = message_time_label(message)
                if timestamp:
                    yield Static(timestamp, classes="event-timestamp")
        if is_always_expanded(message_type):
            if message_type == "error":
                body = error_display_content(message.content, message.metadata)
            else:
                body = message.content
            body = timeline_content(message_type, body)
            content = (
                Markdown(body) if message_type == DEFAULT_MESSAGE_TYPE else body
            )
            yield Static(content or "(empty)", classes="event-body", markup=False)
            return
        if self.expanded:
            disclosure = DISCLOSURE_EXPANDED
            yield Static(
                disclosure,
                classes="event-badge",
                markup=False,
            )
            yield Static(
                timeline_content(message_type, message.content) or "(empty)",
                classes="event-body",
                markup=False,
            )
            pretty = metadata_pretty(message.metadata)
            if pretty is not None:
                yield Static(pretty, classes="event-body", markup=False)
        else:
            preview = timeline_preview(message)
            yield Static(
                f"{preview}  {DISCLOSURE_COLLAPSED}",
                classes="event-preview",
                markup=False,
            )


class RoomRow(ListItem):
    """One room: accent dot, title, star state."""

    DEFAULT_CSS = """
    RoomRow {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    RoomRow .row-dot {
        width: 2;
    }
    RoomRow .row-name {
        width: 1fr;
    }
    RoomRow .row-star {
        width: 2;
    }
    """

    def __init__(self, room: RoomRecord, *, starred: bool) -> None:
        super().__init__()
        self.room = room
        self.starred = starred

    def compose(self) -> ComposeResult:
        yield Static(Text(ROOM_DOT, Style(color=self.room.color)), classes="row-dot")
        yield Label(self.room.title, classes="row-name")
        yield Label(STAR_ON if self.starred else STAR_OFF, classes="row-star")


class IdentityRow(ListItem):
    """Roster/picker entry: avatar, display name and local agent runtime."""

    DEFAULT_CSS = """
    IdentityRow {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    IdentityRow .row-name {
        width: 1fr;
    }
    IdentityRow .row-runtime {
        width: 2;
    }
    """

    def __init__(
        self,
        identity: Identity,
        identity_id: str,
        *,
        runtime: AgentRuntime | None = None,
    ) -> None:
        super().__init__()
        self.identity = identity
        self.identity_id = identity_id
        self.runtime = runtime

    def compose(self) -> ComposeResult:
        yield AvatarChip(self.identity)
        yield Label(self.identity.name, classes="row-name")
        dot_color = (
            RUNNING_DOT_COLOR
            if self.runtime is AgentRuntime.RUNNING
            else STOPPED_DOT_COLOR
        )
        yield Static(
            Text(RUNTIME_DOT, Style(color=dot_color))
            if self.runtime is not None
            else "",
            classes="row-runtime",
        )


def local_runtime(
    identity: AgentRecord | ParticipantRecord, running_ids: frozenset[str]
) -> AgentRuntime | None:
    """The local detached-worker state for an agent; humans have no process state."""
    if identity.kind is AvatarKind.HUMAN:
        return None
    return AgentRuntime.RUNNING if identity.id in running_ids else AgentRuntime.IDLE


class RoomsScreen(ControlScreen):
    """Rooms list: client-side search, starring, creation."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("slash", "focus_search", "Search"),
        Binding("f", "focus_filters", "Filters"),
        Binding("n", "new_room", "New room"),
        Binding("delete", "delete_room", "Delete"),
        Binding("backspace", "delete_room", "Delete", show=False),
        Binding("s", "toggle_star", "Star"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("comma", "app.show_settings", "Settings"),
    ]

    DEFAULT_CSS = """
    RoomsScreen #room-toolbar {
        height: 3;
    }
    RoomsScreen #room-draft {
        display: none;
        height: auto;
        border: round $accent;
        padding: 0 1;
    }
    RoomsScreen #room-draft.open {
        display: block;
    }
    RoomsScreen #room-status {
        height: 1;
        padding: 0 1;
    }
    """

    store: reactive[RoomsStore] = reactive(RoomsStore, always_update=True, init=False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id=Id.TOOLBAR.value):
            yield Input(placeholder=SEARCH_PLACEHOLDER, id=Id.SEARCH.value)
        yield FilterChips(
            ROOM_CHIPS,
            exclusive=True,
            selected=frozenset({RoomFilter.ALL.value}),
            id=Id.FILTERS.value,
        )
        yield ListView(id=Id.LIST.value)
        with Vertical(id=Id.DRAFT.value):
            yield Static(DRAFT_TITLE)
            yield Input(placeholder=DRAFT_PLACEHOLDER, id=Id.DRAFT_TITLE.value)
        yield Static("", id=Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self.store = self.control.rooms_store
        self._pending_delete_id: str | None = None
        self.query_one(selector(Id.LIST), ListView).focus()
        install_catalog_refresh(self, self._refresh_catalog)
        self._load_rooms()

    def on_screen_resume(self) -> None:
        """Keep a view-local draft while navigating between Band surfaces."""
        if not self.is_mounted:
            return
        self._pending_delete_id = None
        self._load_rooms()
        self.mutate_reactive(RoomsScreen.store)

    def _refresh_catalog(self) -> None:
        """Refresh the room catalog only while this surface is visible."""
        if self.is_current:
            self._load_rooms()

    async def watch_store(self, store: RoomsStore) -> None:
        if not self.is_mounted:
            return
        self.query_one(selector(Id.DRAFT), Vertical).set_class(
            store.draft_open, OPEN_CLASS
        )
        visible = store.visible
        list_view = self.query_one(selector(Id.LIST), ListView)
        await list_view.clear()
        await list_view.extend(
            RoomRow(room, starred=store.is_starred(room.id)) for room in visible
        )
        list_view.index = next(
            (
                index
                for index, room in enumerate(visible)
                if room.id == store.selected_id
            ),
            0 if visible else None,
        )
        self.query_one(selector(Id.STATUS), Static).update(
            store.status or ("" if visible else EMPTY_ROOMS)
        )

    # --- search & filters --------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one(selector(Id.SEARCH), Input).focus()

    def action_focus_filters(self) -> None:
        self.query_one(selector(Id.FILTERS), FilterChips).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != Id.SEARCH:
            return
        self.store.set_search(event.value)
        self.mutate_reactive(RoomsScreen.store)

    def on_filter_chips_changed(self, event: FilterChips.Changed) -> None:
        key = next(iter(event.selected), RoomFilter.ALL.value)
        self.store.select_filter(RoomFilter(key))
        self.mutate_reactive(RoomsScreen.store)

    # --- list interactions -------------------------------------------------

    def _highlighted_room(self) -> RoomRecord | None:
        row = self.query_one(selector(Id.LIST), ListView).highlighted_child
        match row:
            case RoomRow(room=room):
                return room
            case _:
                return None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        match event.item:
            case RoomRow(room=room):
                self.store.selected_id = room.id

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        match event.item:
            case RoomRow(room=room):
                self.control.open_room(room)

    def action_toggle_star(self) -> None:
        self._pending_delete_id = None
        room = self._highlighted_room()
        if room is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        self.control.toggle_star(room.id)
        self.mutate_reactive(RoomsScreen.store)

    @work(exclusive=True, group="rooms-load")
    async def _load_rooms(self) -> None:
        store = self.store
        store.loading = True
        try:
            rooms = await list_rooms(self.control.client)
        except Exception as error:
            store.set_status(
                RoomStatusSource.LIST,
                format_platform_error(error, operation="load rooms"),
            )
        else:
            store.replace_rooms(rooms)
            store.clear_status(RoomStatusSource.LIST)
        finally:
            store.loading = False
            self.mutate_reactive(RoomsScreen.store)

    def action_reload(self) -> None:
        self._load_rooms()

    # --- create room (transient overlay) -----------------------------------

    def action_new_room(self) -> None:
        self._pending_delete_id = None
        self.store.draft_open = True
        self.mutate_reactive(RoomsScreen.store)
        self.query_one(selector(Id.DRAFT_TITLE), Input).focus()

    def action_delete_room(self) -> None:
        room = self._highlighted_room()
        if room is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        if self._pending_delete_id != room.id:
            self._pending_delete_id = room.id
            self._set_status(DELETE_CONFIRM_MESSAGE.format(title=room.title))
            return
        self._pending_delete_id = None
        self._delete_room(room)

    @work(exclusive=True, group="rooms-delete")
    async def _delete_room(self, room: RoomRecord) -> None:
        try:
            await self.control.room_operations.delete(room.id)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="delete room"))
            return
        self.control.forget_room(room.id)
        self._set_status(f"Deleted {room.title}.")
        self._load_rooms()

    def action_cancel(self) -> None:
        if self._pending_delete_id is not None:
            self._pending_delete_id = None
            self._set_status("")
            return
        if self.store.draft_open:
            self._close_draft()
            return
        self.query_one(selector(Id.LIST), ListView).focus()

    def _close_draft(self) -> None:
        self.store.discard_draft()
        self.query_one(selector(Id.DRAFT_TITLE), Input).value = ""
        self.mutate_reactive(RoomsScreen.store)
        self.query_one(selector(Id.LIST), ListView).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        match event.input.id:
            case Id.DRAFT_TITLE:
                self._submit_draft()
            case Id.SEARCH:
                self.query_one(selector(Id.LIST), ListView).focus()

    def _submit_draft(self) -> None:
        title = self.query_one(selector(Id.DRAFT_TITLE), Input).value.strip()
        if not title:
            self._set_status(EMPTY_TITLE_MESSAGE)
            return
        self._create_room(title)

    @work(exclusive=True, group="rooms-create")
    async def _create_room(self, title: str) -> None:
        try:
            room = await self.control.room_operations.create(title)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="create room"))
            return
        self.store.add_room(room)
        self.store.clear_status(RoomStatusSource.ACTION)
        self._close_draft()
        self._load_rooms()
        self.control.open_room(room)

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(RoomsScreen.store)


class RoomDetailScreen(ManagedAgentActions, ControlScreen):
    """One room: roster, add-only participant picker, chat."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("a", "add_participant", "Add participant"),
        Binding("x", "remove_participant", "Remove"),
        Binding("delete", "delete_room", "Delete"),
        Binding("backspace", "delete_room", "Delete", show=False),
        Binding("m", "focus_composer", "Compose"),
        Binding("s", "start_participant", "Start"),
        Binding("t", "stop_participant", "Stop"),
        Binding("r", "reload", "Reload"),
        Binding("e", "event_filter", "Events"),
        Binding("v", "toggle_verbose", "Verbose"),
        Binding("d", "event_detail", "Detail"),
        Binding("end", "jump_latest", "Latest", show=False),
        Binding("space", "toggle_chat_expand", "Expand", show=False),
        Binding("escape", "back", "Back"),
        Binding("comma", "app.show_settings", "Settings"),
    ]

    DEFAULT_CSS = """
    RoomDetailScreen #room-heading {
        height: 1;
        padding: 0 1;
    }
    RoomDetailScreen #room-roster {
        width: 34;
        border-right: solid $panel;
    }
    RoomDetailScreen #room-roster > Static {
        padding: 0 1;
    }
    RoomDetailScreen #room-chat-scroll {
        width: 1fr;
    }
    RoomDetailScreen #room-chat-hidden {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    RoomDetailScreen #room-chat {
        height: 1fr;
    }
    RoomDetailScreen #room-chat > ListItem {
        height: auto;
    }
    RoomDetailScreen #room-picker {
        display: none;
        height: auto;
        max-height: 12;
        border: round $accent;
    }
    RoomDetailScreen #room-picker.open {
        display: block;
    }
    RoomDetailScreen #room-detail-status {
        height: 1;
        padding: 0 1;
    }
    """

    store: reactive[RoomsStore] = reactive(RoomsStore, always_update=True, init=False)

    class Incoming(Message):
        """A realtime event for the open room."""

        def __init__(self, event: RealtimeEvent) -> None:
            super().__init__()
            self.event = event

    def __init__(self, room: RoomRecord) -> None:
        super().__init__()
        self.room = room
        self._unsubscribe: Unsubscribe | None = None
        self._pending_delete: bool = False
        self._roster_mutation_pending = False
        self._send_draft: str | None = None
        self._expanded_message_ids: set[str] = set()
        self._rendered_chat: tuple[tuple[MessageRecord, bool], ...] | None = None
        self._rendered_roster: (
            tuple[tuple[ParticipantRecord, AgentRuntime], ...] | None
        ) = None
        self._rendered_candidates: (
            tuple[tuple[AgentRecord, AgentRuntime], ...] | None
        ) = None
        self._unseen_activity = 0
        self._pre_verbose_types: tuple[str, ...] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            Text(f"{ROOM_DOT} {self.room.title}", Style(color=self.room.color)),
            id=Id.HEADING.value,
        )
        with Horizontal():
            with Vertical(id=Id.ROSTER.value):
                yield Static(ROSTER_TITLE)
                yield ListView()
            with Vertical(id=Id.CHAT_SCROLL.value):
                yield Static("", id=Id.CHAT_HIDDEN.value)
                yield ListView(id=Id.CHAT.value)
        with Vertical(id=Id.PICKER.value):
            yield Static(PICKER_TITLE)
            yield ListView(id=Id.PICKER_LIST.value)
        yield MarkdownComposer(placeholder=COMPOSER_PLACEHOLDER, id=Id.COMPOSER.value)
        yield Static("", id=Id.DETAIL_STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self.store = self.control.rooms_store
        self._roster_view().focus()
        self._load_roster()
        self._load_messages()
        self._connect_realtime()

    def on_resize(self, event: Resize) -> None:
        """Keep the roster useful without consuming a narrow terminal."""
        roster = self.query_one(selector(Id.ROSTER), Vertical)
        roster.styles.width = 34 if event.size.width >= 96 else "38%"

    async def on_unmount(self) -> None:
        self._release_realtime_listener()
        await self.control.client.unsubscribe_room(self.room.id)

    def _roster_view(self) -> ListView:
        return self.query_one(selector(Id.ROSTER), Vertical).query_one(ListView)

    async def watch_store(self, store: RoomsStore) -> None:
        if not self.is_mounted:
            return
        self.query_one(selector(Id.PICKER), Vertical).set_class(
            store.picker_open, OPEN_CLASS
        )
        await self._render_roster(store)
        await self._render_picker(store)
        await self._render_chat(store)
        self.query_one(selector(Id.DETAIL_STATUS), Static).update(store.status)

    def _allowed_event_types(self) -> tuple[str, ...]:
        return self.control.preferences.current.chat_event_types

    def _chat_view(self) -> ListView:
        return self.query_one(selector(Id.CHAT), ListView)

    async def _render_chat(self, store: RoomsStore) -> None:
        allowed = self._allowed_event_types()
        visible = visible_messages(store.messages, allowed)
        hidden = hidden_summary(store.messages, allowed)
        chat = self._chat_view()
        following = chat.is_vertical_scroll_end
        timeline = tuple(
            (message, message.id in self._expanded_message_ids) for message in visible
        )
        previous = self._rendered_chat
        message_ids = frozenset(message.id for message, _expanded in timeline)
        previous_ids = (
            frozenset(message.id for message, _expanded in previous)
            if previous is not None
            else frozenset()
        )
        new_count = len(message_ids - previous_ids)
        if previous is not None and new_count and not following:
            self._unseen_activity += new_count
        self._rendered_chat = timeline
        if following:
            self._unseen_activity = 0
        notice = NEW_ACTIVITY_MESSAGE if self._unseen_activity else ""
        self.query_one(selector(Id.CHAT_HIDDEN), Static).update(
            "  ".join(part for part in (hidden, notice) if part)
        )
        if not store.messages:
            rows: list[ListItem] = [ListItem(Static(EMPTY_CHAT))]
        elif not visible:
            rows = [ListItem(Static(FILTERED_EMPTY_CHAT))]
        else:
            rows = [
                ChatEventRow(
                    message,
                    expanded=message.id in self._expanded_message_ids,
                    author_color=store.author_color(message),
                )
                for message in visible
            ]
        if previous == timeline:
            return
        if previous and timeline[: len(previous)] == previous:
            await chat.extend(rows[-new_count:])
        else:
            await refill(chat, rows)
        if following:
            chat.scroll_end(animate=False)

    def action_jump_latest(self) -> None:
        self._unseen_activity = 0
        self._chat_view().scroll_end(animate=False)
        self.query_one(selector(Id.CHAT_HIDDEN), Static).update(
            hidden_summary(self.store.messages, self._allowed_event_types())
        )

    async def _render_roster(self, store: RoomsStore) -> None:
        running_ids = self.control.agents_store.running_ids
        roster = tuple(
            (participant, local_runtime(participant, running_ids))
            for participant in store.participants
        )
        if roster == self._rendered_roster:
            return
        self._rendered_roster = roster
        self.query_one(selector(Id.COMPOSER), MarkdownComposer).set_mention_handles(
            key
            for participant in store.participants
            for key in mention_keys(participant)
        )
        await refill(
            self._roster_view(),
            [
                IdentityRow(participant, participant.id, runtime=runtime)
                for participant, runtime in roster
            ],
        )

    async def _render_picker(self, store: RoomsStore) -> None:
        running_ids = self.control.agents_store.running_ids
        candidates = tuple(
            (candidate, local_runtime(candidate, running_ids))
            for candidate in store.addable_candidates()
        )
        if candidates == self._rendered_candidates:
            return
        self._rendered_candidates = candidates
        await refill(
            self.query_one(selector(Id.PICKER_LIST), ListView),
            [
                IdentityRow(candidate, candidate.id, runtime=runtime)
                for candidate, runtime in candidates
            ],
        )

    # --- roster ------------------------------------------------------------

    @work(exclusive=True, group="room-roster")
    async def _load_roster(self) -> None:
        store = self.store
        try:
            participants = await self.control.client.list_participants(self.room.id)
        except Exception as error:
            store.set_status(
                RoomStatusSource.ROSTER,
                format_platform_error(error, operation="load room roster"),
            )
        else:
            store.replace_participants(
                order_roster(
                    participants,
                    user_id=self.control.user_id,
                    local_agent_ids=self.control.managed_agents.ids(),
                )
            )
            store.clear_status(RoomStatusSource.ROSTER)
        self.mutate_reactive(RoomDetailScreen.store)

    def action_reload(self) -> None:
        self._pending_delete = False
        self._load_roster()
        self._load_messages()
        self._load_candidates()
        self._connect_realtime()

    def action_delete_room(self) -> None:
        if not self._pending_delete:
            self._pending_delete = True
            self._set_status(DELETE_CONFIRM_MESSAGE.format(title=self.room.title))
            return
        self._pending_delete = False
        self._delete_room()

    @work(exclusive=True, group="room-delete")
    async def _delete_room(self) -> None:
        try:
            await self.control.room_operations.delete(self.room.id)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="delete room"))
            return
        title = self.room.title
        self.control.forget_room(self.room.id)
        self.control.rooms_store.status = f"Deleted {title}."
        self.app.pop_screen()

    @work(exclusive=True, group="room-messages")
    async def _load_messages(self) -> None:
        store = self.store
        try:
            messages = await self.control.client.list_messages(
                self.room.id,
                limit=self.control.preferences.current.chat_messages_limit,
            )
        except Exception as error:
            store.set_status(
                RoomStatusSource.MESSAGES,
                format_platform_error(error, operation="load room messages"),
            )
        else:
            store.replace_messages(messages)
            store.clear_status(RoomStatusSource.MESSAGES)
        self.mutate_reactive(RoomDetailScreen.store)

    def _highlighted_identity_id(self, list_view: ListView) -> str | None:
        row = list_view.highlighted_child
        match row:
            case IdentityRow(identity_id=identity_id):
                return identity_id
            case _:
                return None

    def _highlighted_agent_participant(self) -> ParticipantRecord | None:
        row = self._roster_view().highlighted_child
        match row:
            case IdentityRow(identity=ParticipantRecord() as participant) if (
                participant.kind is AvatarKind.AGENT
            ):
                return participant
            case _:
                return None

    def _agent_record_for(self, participant: ParticipantRecord) -> AgentRecord:
        profile = self.control.managed_agents.get(participant.id)
        return AgentRecord(
            id=participant.id,
            name=participant.name,
            kind=participant.kind,
            color=participant.color,
            harness=profile.harness if profile is not None else None,
        )

    def action_start_participant(self) -> None:
        participant = self._highlighted_agent_participant()
        if participant is None:
            self._set_status(NO_AGENT_PARTICIPANT_MESSAGE)
            return
        self.start_managed_agent(self._agent_record_for(participant))

    def action_stop_participant(self) -> None:
        participant = self._highlighted_agent_participant()
        if participant is None:
            self._set_status(NO_AGENT_PARTICIPANT_MESSAGE)
            return
        self.stop_managed_agent(participant.id, participant.name)

    def _set_agent_operation_status(self, status: str) -> None:
        self._set_status(status)

    def _refresh_agent_operation_view(self) -> None:
        self.mutate_reactive(RoomDetailScreen.store)

    def action_remove_participant(self) -> None:
        """Instant removal — no confirmation step by design."""
        self._pending_delete = False
        if not self._begin_roster_mutation():
            return
        participant_id = self._highlighted_identity_id(self._roster_view())
        if participant_id is None:
            self._roster_mutation_pending = False
            self._set_status(NO_PARTICIPANT_MESSAGE)
            return
        self.store.remove_participant(participant_id)
        self.mutate_reactive(RoomDetailScreen.store)
        self._remove_participant(participant_id)

    @work(group="room-participants")
    async def _remove_participant(self, participant_id: str) -> None:
        try:
            await self.control.client.remove_participant(self.room.id, participant_id)
        except Exception as error:
            self._set_status(
                format_platform_error(error, operation="remove participant")
            )
        finally:
            self._roster_mutation_pending = False
            self._load_roster()
            self._load_candidates()

    # --- add participant (select-then-act, add-only) -----------------------

    def action_add_participant(self) -> None:
        self._pending_delete = False
        self._set_picker_open(True)
        self._load_candidates()

    def _set_picker_open(self, is_open: bool) -> None:
        self.store.picker_open = is_open
        self.mutate_reactive(RoomDetailScreen.store)
        picker = self.query_one(selector(Id.PICKER_LIST), ListView)
        (picker if is_open else self._roster_view()).focus()

    @work(exclusive=True, group="room-candidates")
    async def _load_candidates(self) -> None:
        store = self.store
        try:
            store.candidates = await self.control.client.list_my_agents()
        except Exception as error:
            store.set_status(
                RoomStatusSource.PARTICIPANTS,
                format_platform_error(error, operation="load participants"),
            )
        else:
            store.set_status(
                RoomStatusSource.PARTICIPANTS,
                "" if store.addable_candidates() else EMPTY_CANDIDATES,
            )
        self.mutate_reactive(RoomDetailScreen.store)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == Id.CHAT and isinstance(event.item, ChatEventRow):
            self._toggle_chat_expand(event.item)
            return
        if event.list_view.id != Id.PICKER_LIST or not isinstance(
            event.item, IdentityRow
        ):
            return
        # A ListView selection can originate from a mouse-up event.  Do not
        # refill or hide that ListView until Textual has finished dispatching it.
        self.call_after_refresh(self._select_candidate, event.item.identity_id)

    def _select_candidate(self, participant_id: str) -> None:
        if self._begin_roster_mutation():
            self._set_picker_open(False)
            self._add_participant(participant_id)

    @work(group="room-participants")
    async def _add_participant(self, participant_id: str) -> None:
        """Add-only: an agent already elsewhere is never re-parented."""
        try:
            await self.control.client.add_participant(self.room.id, participant_id)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="add participant"))
            return
        finally:
            self._roster_mutation_pending = False
            self._load_roster()
            self._load_candidates()

    def _begin_roster_mutation(self) -> bool:
        if self._roster_mutation_pending:
            self._set_status(ROSTER_UPDATING_MESSAGE)
            return False
        self._roster_mutation_pending = True
        return True

    # --- chat --------------------------------------------------------------

    def action_event_filter(self) -> None:
        self.app.push_screen(
            EventTypeFilterScreen(
                self._allowed_event_types(),
                self.store.messages,
                self._apply_event_filter,
            )
        )

    def _apply_event_filter(self, allowed: tuple[str, ...]) -> None:
        self._pre_verbose_types = None
        self.control.preferences.update(chat_event_types=allowed)
        self.mutate_reactive(RoomDetailScreen.store)

    def action_toggle_verbose(self) -> None:
        current = self._allowed_event_types()
        if verbose_active(current):
            restored = apply_verbose(
                current, enabled=False, previous=self._pre_verbose_types
            )
            self._pre_verbose_types = None
            self.control.preferences.update(chat_event_types=restored)
        else:
            self._pre_verbose_types = current
            self.control.preferences.update(
                chat_event_types=apply_verbose(current, enabled=True, previous=None)
            )
        self.mutate_reactive(RoomDetailScreen.store)

    def action_event_detail(self) -> None:
        row = self._chat_view().highlighted_child
        if not isinstance(row, ChatEventRow):
            return
        self.app.push_screen(ChatEventDetailScreen(row.message))

    def action_toggle_chat_expand(self) -> None:
        chat = self._chat_view()
        if not chat.has_focus:
            return
        row = chat.highlighted_child
        if isinstance(row, ChatEventRow):
            self._toggle_chat_expand(row)

    def _toggle_chat_expand(self, row: ChatEventRow) -> None:
        message = row.message
        if is_always_expanded(message.message_type or DEFAULT_MESSAGE_TYPE):
            return
        if message.id in self._expanded_message_ids:
            self._expanded_message_ids.discard(message.id)
        else:
            self._expanded_message_ids.add(message.id)
        self.mutate_reactive(RoomDetailScreen.store)

    def action_focus_composer(self) -> None:
        self.query_one(selector(Id.COMPOSER), MarkdownComposer).focus()

    def action_back(self) -> None:
        """Escape unwinds one level: picker, then composer, then the room."""
        if self._pending_delete:
            self._pending_delete = False
            self._set_status("")
            return
        if self.store.picker_open:
            self._set_picker_open(False)
            return
        if self.query_one(selector(Id.COMPOSER), MarkdownComposer).has_focus:
            self._roster_view().focus()
            return
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != Id.COMPOSER:
            return
        body = event.value.strip()
        resolved = resolve_mentions(body, self.store.participants)
        if resolved is None:
            self._set_status(MENTION_REQUIRED_MESSAGE)
            return
        mentioned, remainder = resolved
        if self._send_draft is not None:
            return
        self._send_draft = event.input.value
        self._send_message(mentioned, remainder, event.input.value)

    @work(group="room-send")
    async def _send_message(
        self, mentioned: list[ParticipantRecord], body: str, draft: str
    ) -> None:
        try:
            message = await self.control.client.send_message(
                self.room.id,
                body,
                mentions=[
                    (participant.id, participant.name) for participant in mentioned
                ],
                sender_name=self._host_author_name(),
            )
        except Exception as error:
            self._set_status(format_platform_error(error, operation="send message"))
            return
        else:
            composer = self.query_one(selector(Id.COMPOSER), MarkdownComposer)
            if composer.value == draft:
                composer.value = ""
            self.store.append_message(message)
            self.store.clear_status(RoomStatusSource.ACTION)
            self.mutate_reactive(RoomDetailScreen.store)
        finally:
            self._send_draft = None

    # --- realtime ----------------------------------------------------------

    @work(exclusive=True, group="room-realtime")
    async def _connect_realtime(self) -> None:
        self._release_realtime_listener()
        unsubscribe = self.control.client.subscribe_realtime(self._on_event)
        try:
            await self.control.client.subscribe_room(self.room.id)
        except BaseException as error:
            unsubscribe()
            if isinstance(error, asyncio.CancelledError):
                raise
            self.store.set_status(
                RoomStatusSource.REALTIME,
                format_platform_error(error, operation="connect realtime"),
            )
            self.mutate_reactive(RoomDetailScreen.store)
        else:
            self._unsubscribe = unsubscribe
            self.store.clear_status(RoomStatusSource.REALTIME)
            self.mutate_reactive(RoomDetailScreen.store)

    def _release_realtime_listener(self) -> None:
        if self._unsubscribe is None:
            return
        self._unsubscribe()
        self._unsubscribe = None

    def _on_event(self, event: RealtimeEvent) -> None:
        self.post_message(self.Incoming(event))

    def on_room_detail_screen_incoming(self, event: RoomDetailScreen.Incoming) -> None:
        if event.event.room_id != self.room.id:
            return
        if event.event.kind in _ROSTER_EVENT_KINDS:
            self._load_roster()
            return
        message = message_from_event(event.event)
        if message is None:
            return
        self.store.append_message(message)
        self.mutate_reactive(RoomDetailScreen.store)

    def _host_author_name(self) -> str:
        """Roster display name for the signed-in human, else a stable fallback."""
        user_id = self.control.user_id
        if user_id is not None:
            for participant in self.store.participants:
                if participant.id == user_id:
                    return participant.name
        return "You"

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(RoomDetailScreen.store)
