"""Default workspace: adjacent, live agents and rooms catalogs."""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListView, Static

from band_wezterm.errors import format_platform_error
from band_wezterm.tui.catalog_loaders import list_rooms
from band_wezterm.tui.refresh import CATALOG_POLL_SECONDS
from band_wezterm.tui.screens import agents, rooms
from band_wezterm.tui.stores import (
    AgentFilter,
    AgentSource,
    RoomFilter,
    RoomsStore,
    RoomStatusSource,
)
from band_wezterm.tui.widgets import FilterChips

AGENTS_HEADING = "Agents"
ROOMS_HEADING = "Rooms"
WORKSPACE_PANELS_ID = "workspace-panels"
WORKSPACE_AGENTS_ID = "workspace-agents"
WORKSPACE_ROOMS_ID = "workspace-rooms"
AGENT_ACTION_SELECTION_MESSAGE = "Select an agent in the Agents pane first."


class WorkspaceScreen(agents.AgentsScreen):
    """Side-by-side catalog projection backed by the shared app stores."""

    DEFAULT_CSS = """
    WorkspaceScreen #workspace-panels {
        height: 1fr;
    }
    WorkspaceScreen #workspace-agents {
        width: 1fr;
        border-right: solid $panel;
    }
    WorkspaceScreen #workspace-rooms {
        width: 1fr;
    }
    WorkspaceScreen .workspace-heading {
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    WorkspaceScreen #agent-toolbar,
    WorkspaceScreen #room-toolbar {
        height: 3;
    }
    WorkspaceScreen #agent-source {
        width: 18;
        content-align: right middle;
    }
    WorkspaceScreen #agent-status,
    WorkspaceScreen #room-status {
        height: 1;
        padding: 0 1;
    }
    """

    rooms: reactive[RoomsStore] = reactive(RoomsStore, always_update=True, init=False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id=WORKSPACE_PANELS_ID):
            with Vertical(id=WORKSPACE_AGENTS_ID):
                yield Label(AGENTS_HEADING, classes="workspace-heading")
                with Horizontal(id=agents.Id.TOOLBAR.value):
                    yield Input(
                        placeholder=agents.SEARCH_PLACEHOLDER,
                        id=agents.Id.SEARCH.value,
                    )
                    yield Static(
                        agents.SOURCE_LABELS[AgentSource.MINE],
                        id=agents.Id.SOURCE.value,
                    )
                yield FilterChips(
                    agents.AGENT_CHIPS,
                    exclusive=True,
                    selected=frozenset({AgentFilter.ALL.value}),
                    id=agents.Id.FILTERS.value,
                )
                yield ListView(id=agents.Id.LIST.value)
                yield Static("", id=agents.Id.STATUS.value)
            with Vertical(id=WORKSPACE_ROOMS_ID):
                yield Label(ROOMS_HEADING, classes="workspace-heading")
                with Horizontal(id=rooms.Id.TOOLBAR.value):
                    yield Input(
                        placeholder=rooms.SEARCH_PLACEHOLDER,
                        id=rooms.Id.SEARCH.value,
                    )
                yield FilterChips(
                    rooms.ROOM_CHIPS,
                    exclusive=True,
                    selected=frozenset({RoomFilter.ALL.value}),
                    id=rooms.Id.FILTERS.value,
                )
                yield ListView(id=rooms.Id.LIST.value)
                yield Static("", id=rooms.Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        super().on_mount()
        self.rooms = self.control.rooms_store
        self.set_interval(CATALOG_POLL_SECONDS, self._load_rooms)
        self._load_rooms()

    def on_screen_resume(self) -> None:
        super().on_screen_resume()
        self._load_rooms()
        self.mutate_reactive(WorkspaceScreen.rooms)

    async def watch_rooms(self, store: RoomsStore) -> None:
        if not self.is_mounted:
            return
        visible = store.visible
        list_view = self.query_one(rooms.selector(rooms.Id.LIST), ListView)
        await list_view.clear()
        await list_view.extend(
            rooms.RoomRow(room, starred=store.is_starred(room.id)) for room in visible
        )
        list_view.index = next(
            (
                index
                for index, room in enumerate(visible)
                if room.id == store.selected_id
            ),
            0 if visible else None,
        )
        self.query_one(rooms.selector(rooms.Id.STATUS), Static).update(
            store.status or ("" if visible else rooms.EMPTY_ROOMS)
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        match event.input.id:
            case agents.Id.SEARCH:
                super().on_input_changed(event)
            case rooms.Id.SEARCH:
                self.rooms.set_search(event.value)
                self.mutate_reactive(WorkspaceScreen.rooms)

    def on_filter_chips_changed(self, event: FilterChips.Changed) -> None:
        match event.chips.id:
            case agents.Id.FILTERS:
                super().on_filter_chips_changed(event)
            case rooms.Id.FILTERS:
                key = next(iter(event.selected), RoomFilter.ALL.value)
                self.rooms.select_filter(RoomFilter(key))
                self.mutate_reactive(WorkspaceScreen.rooms)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        super().on_list_view_highlighted(event)
        if isinstance(event.item, rooms.RoomRow):
            self.rooms.selected_id = event.item.room.id

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, rooms.RoomRow):
            self.control.open_room(event.item.room)

    def _agent_action_available(self) -> bool:
        focused = self.app.focused
        agents_panel = self.query_one(f"#{WORKSPACE_AGENTS_ID}", Vertical)
        if focused is not None and agents_panel in focused.ancestors_with_self:
            return True
        self.rooms.set_status(
            RoomStatusSource.ACTION, AGENT_ACTION_SELECTION_MESSAGE
        )
        self.mutate_reactive(WorkspaceScreen.rooms)
        return False

    def action_new_agent(self) -> None:
        if self._agent_action_available():
            super().action_new_agent()

    def action_reconfigure_agent(self) -> None:
        if self._agent_action_available():
            super().action_reconfigure_agent()

    def action_delete_agent(self) -> None:
        if self._agent_action_available():
            super().action_delete_agent()

    def action_start_agent(self) -> None:
        if self._agent_action_available():
            super().action_start_agent()

    def action_stop_agent(self) -> None:
        if self._agent_action_available():
            super().action_stop_agent()

    def action_open_role_library(self) -> None:
        if self._agent_action_available():
            super().action_open_role_library()

    def action_new_role(self) -> None:
        if self._agent_action_available():
            super().action_new_role()

    def action_toggle_discover(self) -> None:
        if self._agent_action_available():
            super().action_toggle_discover()

    @work(exclusive=True, group="workspace-rooms-load")
    async def _load_rooms(self) -> None:
        store = self.rooms
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
            self.mutate_reactive(WorkspaceScreen.rooms)

    def action_reload(self) -> None:
        super().action_reload()
        self._load_rooms()
