"""Rooms — list, starring, creation, roster management and chat."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import ClassVar, Final

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
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
from band_wezterm.tui.screens import ControlScreen
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
EMPTY_CANDIDATES: Final = "Every one of your agents is already in this room."
NO_SELECTION_MESSAGE: Final = "Select a room first."
NO_PARTICIPANT_MESSAGE: Final = "Select a participant first."
MENTION_REQUIRED_MESSAGE: Final = "Messages must @mention a room participant."
EMPTY_TITLE_MESSAGE: Final = "A room title is required."
DELETE_CONFIRM_MESSAGE: Final = (
    "Press Delete again to permanently remove {title}."
)

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
    COMPOSER = "room-composer"
    DETAIL_STATUS = "room-detail-status"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


def mention_keys(participant: ParticipantRecord) -> tuple[str, ...]:
    """Accepted composer keys: the true handle and the visible roster name."""
    keys = (participant.handle, participant.name)
    return tuple(dict.fromkeys(key for key in keys if key))


def resolve_mention(
    body: str, participants: Iterable[ParticipantRecord]
) -> tuple[ParticipantRecord, str] | None:
    """First canonical `@handle` that names a participant, plus the remaining body."""
    candidates = sorted(
        (
            (key, participant)
            for participant in participants
            for key in mention_keys(participant)
        ),
        key=lambda candidate: len(candidate[0]),
        reverse=True,
    )
    for key, participant in candidates:
        match = re.search(
            rf"(?<!\S)@{re.escape(key)}(?=\s|$)", body, flags=re.IGNORECASE
        )
        if match is not None:
            remainder = f"{body[: match.start()]} {body[match.end() :]}".strip()
            return participant, remainder
    return None


def chat_markdown(messages: Iterable[MessageRecord]) -> str:
    rendered = [
        f"**{message.author_name}**\n\n{message.content}" for message in messages
    ]
    return "\n\n---\n\n".join(rendered) or EMPTY_CHAT


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
    }
)


def message_from_event(event: RealtimeEvent) -> MessageRecord | None:
    if event.kind not in _MESSAGE_EVENT_KINDS:
        return None
    payload = event.payload or {}
    content = payload.get("content") or payload.get("body")
    if not content:
        return None
    metadata = payload.get("metadata")
    meta = metadata if isinstance(metadata, dict) else None
    return MessageRecord(
        id=str(payload.get("id") or event.kind.value),
        content=display_message_content(str(content), meta),
        author_name=str(
            payload.get("sender_name")
            or payload.get("author_name")
            or payload.get("sender")
            or "unknown"
        ),
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
            Text(RUNTIME_DOT, Style(color=dot_color)) if self.runtime is not None else "",
            classes="row-runtime",
        )


def local_runtime(
    identity: AgentRecord | ParticipantRecord, running_ids: frozenset[str]
) -> AgentRuntime | None:
    """The local WezTerm-pane state for an agent; humans have no process state."""
    if identity.kind is AvatarKind.HUMAN:
        return None
    return AgentRuntime.RUNNING if identity.id in running_ids else AgentRuntime.IDLE


class RoomsScreen(ControlScreen):
    """Rooms list: client-side search, starring, creation."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+a", "app.show_agents", "Agents", show=False),
        Binding("ctrl+o", "app.show_rooms", "Rooms", show=False),
        Binding("slash", "focus_search", "Search"),
        Binding("f", "focus_filters", "Filters"),
        Binding("n", "new_room", "New room"),
        Binding("delete", "delete_room", "Delete"),
        Binding("backspace", "delete_room", "Delete", show=False),
        Binding("s", "toggle_star", "Star"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "cancel", "Cancel", show=False),
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
        self._load_rooms()

    def on_screen_resume(self) -> None:
        """A draft never survives leaving the screen — reopen it from scratch."""
        if not self.is_mounted:
            return
        self._pending_delete_id = None
        self._close_draft()
        self.mutate_reactive(RoomsScreen.store)

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
        self.store.search = event.value
        self.mutate_reactive(RoomsScreen.store)

    def on_filter_chips_changed(self, event: FilterChips.Changed) -> None:
        key = next(iter(event.selected), RoomFilter.ALL.value)
        self.store.select_filter(RoomFilter(key))
        self.mutate_reactive(RoomsScreen.store)

    # --- list interactions -------------------------------------------------

    def _highlighted_room(self) -> RoomRecord | None:
        row = self.query_one(selector(Id.LIST), ListView).highlighted_child
        return row.room if isinstance(row, RoomRow) else None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, RoomRow):
            self.store.selected_id = event.item.room.id

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, RoomRow):
            self.control.open_room(event.item.room)

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
            rooms = await self.control.client.list_my_chats()
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
            await self.control.client.delete_room(room.id)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="delete room"))
            return
        self.control.forget_room(room.id)
        self._set_status(f"Deleted {room.title}.")

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
            room = await self.control.client.create_room(title=title)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="create room"))
            return
        self.store.add_room(room)
        self.store.clear_status(RoomStatusSource.ACTION)
        self._close_draft()
        self.control.open_room(room)

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(RoomsScreen.store)


class RoomDetailScreen(ControlScreen):
    """One room: roster, add-only participant picker, chat."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+a", "app.show_agents", "Agents", show=False),
        Binding("ctrl+o", "app.show_rooms", "Rooms", show=False),
        Binding("a", "add_participant", "Add participant"),
        Binding("x", "remove_participant", "Remove"),
        Binding("delete", "delete_room", "Delete"),
        Binding("backspace", "delete_room", "Delete", show=False),
        Binding("m", "focus_composer", "Compose"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "back", "Back"),
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
            with VerticalScroll(id=Id.CHAT_SCROLL.value):
                yield Markdown(EMPTY_CHAT, id=Id.CHAT.value)
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

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

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
        await self.query_one(selector(Id.CHAT), Markdown).update(
            chat_markdown(store.messages)
        )
        self.query_one(selector(Id.CHAT_SCROLL), VerticalScroll).scroll_end(
            animate=False
        )
        self.query_one(selector(Id.DETAIL_STATUS), Static).update(store.status)

    async def _render_roster(self, store: RoomsStore) -> None:
        running_ids = self.control.agents_store.running_ids
        self.query_one(selector(Id.COMPOSER), MarkdownComposer).set_mention_handles(
            key for participant in store.participants for key in mention_keys(participant)
        )
        await refill(
            self._roster_view(),
            [
                IdentityRow(
                    participant,
                    participant.id,
                    runtime=local_runtime(participant, running_ids),
                )
                for participant in store.participants
            ],
        )

    async def _render_picker(self, store: RoomsStore) -> None:
        running_ids = self.control.agents_store.running_ids
        await refill(
            self.query_one(selector(Id.PICKER_LIST), ListView),
            [
                IdentityRow(
                    candidate,
                    candidate.id,
                    runtime=local_runtime(candidate, running_ids),
                )
                for candidate in store.addable_candidates()
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
            store.replace_participants(participants)
            store.clear_status(RoomStatusSource.ROSTER)
        self.mutate_reactive(RoomDetailScreen.store)

    def action_reload(self) -> None:
        self._pending_delete = False
        self._load_roster()
        self._load_messages()

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
            await self.control.client.delete_room(self.room.id)
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
        return row.identity_id if isinstance(row, IdentityRow) else None

    def action_remove_participant(self) -> None:
        """Instant removal — no confirmation step by design."""
        self._pending_delete = False
        participant_id = self._highlighted_identity_id(self._roster_view())
        if participant_id is None:
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
            self._load_roster()

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
                "" if store.addable_candidates() else EMPTY_CANDIDATES
            )
        self.mutate_reactive(RoomDetailScreen.store)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != Id.PICKER_LIST or not isinstance(
            event.item, IdentityRow
        ):
            return
        self._add_participant(event.item.identity_id)

    @work(group="room-participants")
    async def _add_participant(self, participant_id: str) -> None:
        """Add-only: an agent already elsewhere is never re-parented."""
        try:
            await self.control.client.add_participant(self.room.id, participant_id)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="add participant"))
            return
        self._set_picker_open(False)
        self._load_roster()

    # --- chat --------------------------------------------------------------

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
        mention = resolve_mention(body, self.store.participants)
        if mention is None:
            self._set_status(MENTION_REQUIRED_MESSAGE)
            return
        participant, remainder = mention
        event.input.value = ""
        self._send_message(participant, remainder)

    @work(group="room-send")
    async def _send_message(
        self, participant: ParticipantRecord, body: str
    ) -> None:
        try:
            message = await self.control.client.send_message(
                self.room.id,
                body,
                mention_id=participant.id,
                mention_name=participant.name,
            )
        except Exception as error:
            self._set_status(format_platform_error(error, operation="send message"))
            return
        self.store.append_message(message)
        self.store.clear_status(RoomStatusSource.ACTION)
        self.mutate_reactive(RoomDetailScreen.store)

    # --- realtime ----------------------------------------------------------

    @work(exclusive=True, group="room-realtime")
    async def _connect_realtime(self) -> None:
        try:
            self._unsubscribe = self.control.client.subscribe_realtime(self._on_event)
            await self.control.client.subscribe_room(self.room.id)
        except Exception as error:
            self.store.set_status(
                RoomStatusSource.REALTIME,
                format_platform_error(error, operation="connect realtime"),
            )
            self.mutate_reactive(RoomDetailScreen.store)
        else:
            self.store.clear_status(RoomStatusSource.REALTIME)
            self.mutate_reactive(RoomDetailScreen.store)

    def _on_event(self, event: RealtimeEvent) -> None:
        self.post_message(self.Incoming(event))

    def on_room_detail_screen_incoming(self, event: RoomDetailScreen.Incoming) -> None:
        if event.event.room_id != self.room.id:
            return
        message = message_from_event(event.event)
        if message is None:
            return
        self.store.append_message(message)
        self.mutate_reactive(RoomDetailScreen.store)

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(RoomDetailScreen.store)
