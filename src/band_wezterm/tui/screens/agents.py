"""Agents catalog — search, filter chips, registration, start/stop, discover."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import ClassVar, Final

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from band_wezterm.client import AgentRecord
from band_wezterm.errors import format_platform_error, is_missing_resource
from band_wezterm.identity import AgentRuntime, HarnessBadge, harness_badge
from band_wezterm.role_library import open_role_library
from band_wezterm.supervisor.protocol import WorkerState
from band_wezterm.tui.catalog_loaders import list_managed_agents
from band_wezterm.tui.managed_agent_actions import (
    AGENT_STARTING_MESSAGE,
    ManagedAgentActions,
)
from band_wezterm.tui.refresh import install_catalog_refresh
from band_wezterm.tui.screens import ControlScreen
from band_wezterm.tui.screens.new_role import NewRoleScreen
from band_wezterm.tui.screens.register_agent import RegisterAgentScreen
from band_wezterm.tui.stores import (
    AGENT_FILTER_LABELS,
    AgentFilter,
    AgentSource,
    AgentsStore,
    AgentStatusSource,
)
from band_wezterm.tui.widgets import AvatarChip, Chip, FilterChips

NO_BADGE: Final = "  "

SEARCH_DEBOUNCE_SECONDS: Final = 0.25

SEARCH_PLACEHOLDER: Final = "Search agents by name"
SOURCE_LABELS: Final[dict[AgentSource, str]] = {
    AgentSource.MINE: "My agents",
    AgentSource.DIRECTORY: "Discover · public directory",
}
EMPTY_CATALOG: Final = "No agents match the current search and filter."
NO_SELECTION_MESSAGE: Final = "Select an agent first."
DELETE_CONFIRM_MESSAGE: Final = "Press Delete again to permanently remove {name}."
REFRESHING_AGENTS_MESSAGE: Final = "Refreshing agents…"
REFRESHED_AGENTS_MESSAGE: Final = "Refreshed {count} agents."
REFRESHING_DIRECTORY_MESSAGE: Final = "Refreshing public directory…"
REFRESHED_DIRECTORY_MESSAGE: Final = "Refreshed {count} public agents."
DELETING_AGENT_MESSAGE: Final = "Deleting {name}…"
STALE_AGENT_REMOVED_MESSAGE: Final = (
    "{name} was already deleted remotely — removed the stale local entry."
)
DELETING_LABEL: Final = "deleting"
OPERATION_IN_PROGRESS_MESSAGE: Final = "An agent operation is already in progress."
NEW_ROLE_PROMPT: Final = "New role name"


class Id(StrEnum):
    """Widget ids owned by this screen."""

    SEARCH = "agent-search"
    FILTERS = "agent-filters"
    SOURCE = "agent-source"
    LIST = "agent-list"
    STATUS = "agent-status"
    TOOLBAR = "agent-toolbar"


AGENT_CHIPS: Final[tuple[Chip, ...]] = tuple(
    Chip(key=chip.value, label=label) for chip, label in AGENT_FILTER_LABELS.items()
)


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


def badge_for(agent: AgentRecord) -> HarnessBadge | None:
    """Badge letters for a known harness; nothing to show without one."""
    return harness_badge(agent.harness) if agent.harness is not None else None


def badge_label(agent: AgentRecord) -> str:
    badge = badge_for(agent)
    return badge.value if badge is not None else NO_BADGE


class AgentRow(ListItem):
    """One catalog entry: avatar, name, harness badge, run state."""

    DEFAULT_CSS = """
    AgentRow {
        layout: horizontal;
        height: 1;
        padding: 0 1;
    }
    AgentRow .row-name {
        width: 1fr;
    }
    AgentRow .row-badge {
        width: 4;
    }
    AgentRow .row-state {
        width: 9;
    }
    """

    def __init__(
        self,
        agent: AgentRecord,
        *,
        running: bool,
        worker_state: WorkerState | None = None,
        deleting: bool = False,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.running = running
        self.worker_state = worker_state
        self.deleting = deleting

    def compose(self) -> ComposeResult:
        yield AvatarChip(self.agent)
        yield Label(self.agent.name, classes="row-name")
        yield Label(badge_label(self.agent), classes="row-badge")
        yield Label(
            (
                DELETING_LABEL
                if self.deleting
                else (
                    self.worker_state.value
                    if self.worker_state is not None
                    else (
                        AgentRuntime.RUNNING if self.running else AgentRuntime.IDLE
                    ).value
                )
            ),
            classes="row-state",
        )


class AgentsScreen(ManagedAgentActions, ControlScreen):
    """Keyboard-first agents catalog projected from ``AgentsStore``."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("slash", "focus_search", "Search"),
        Binding("f", "focus_filters", "Filters"),
        Binding("n", "new_agent", "Register"),
        Binding("c", "reconfigure_agent", "Reconfigure"),
        Binding("delete", "delete_agent", "Delete"),
        Binding("backspace", "delete_agent", "Delete", show=False),
        Binding("s", "start_agent", "Start"),
        Binding("x", "stop_agent", "Stop"),
        Binding("o", "open_role_library", "Roles"),
        Binding("w", "new_role", "New role"),
        Binding("d", "toggle_discover", "Discover"),
        Binding("r", "reload", "Reload"),
        Binding("comma", "app.show_settings", "Settings"),
    ]

    DEFAULT_CSS = """
    AgentsScreen #agent-toolbar {
        height: 3;
    }
    AgentsScreen #agent-source {
        width: 28;
        content-align: right middle;
    }
    AgentsScreen #agent-status {
        height: 1;
        padding: 0 1;
    }
    """

    store: reactive[AgentsStore] = reactive(AgentsStore, always_update=True, init=False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id=Id.TOOLBAR.value):
            yield Input(placeholder=SEARCH_PLACEHOLDER, id=Id.SEARCH.value)
            yield Static(SOURCE_LABELS[AgentSource.MINE], id=Id.SOURCE.value)
        yield FilterChips(
            AGENT_CHIPS,
            exclusive=True,
            selected=frozenset({AgentFilter.ALL.value}),
            id=Id.FILTERS.value,
        )
        yield ListView(id=Id.LIST.value)
        yield Static("", id=Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self.store = self.control.agents_store
        self._pending_delete_id: str | None = None
        self.query_one(selector(Id.LIST), ListView).focus()
        install_catalog_refresh(self, self._refresh_catalog)
        self._load_agents()

    def on_screen_resume(self) -> None:
        """Return focus to the catalog after an overlay closes."""
        if not self.is_mounted:
            return
        self.query_one(selector(Id.LIST), ListView).focus()
        self._refresh_catalog()

    async def watch_store(self, store: AgentsStore) -> None:
        if not self.is_current:
            return
        self.query_one(selector(Id.SOURCE), Static).update(SOURCE_LABELS[store.source])
        await self._render_rows(store)

    async def _render_rows(self, store: AgentsStore) -> None:
        visible = store.visible
        list_view = self.query_one(selector(Id.LIST), ListView)
        await list_view.clear()
        await list_view.extend(
            AgentRow(
                agent,
                running=store.is_running(agent.id),
                worker_state=store.worker_state(agent.id),
                deleting=store.is_deleting(agent.id),
            )
            for agent in visible
        )
        list_view.index = next(
            (
                index
                for index, agent in enumerate(visible)
                if agent.id == store.selected_id
            ),
            0 if visible else None,
        )
        fallback_status = (
            REFRESHING_AGENTS_MESSAGE
            if store.loading
            else ("" if visible else EMPTY_CATALOG)
        )
        self.query_one(selector(Id.STATUS), Static).update(
            store.status or ("" if visible else fallback_status)
        )

    # --- selection ---------------------------------------------------------

    def _highlighted_agent(self) -> AgentRecord | None:
        row = self.query_one(selector(Id.LIST), ListView).highlighted_child
        match row:
            case AgentRow(agent=agent):
                return agent
            case _:
                return None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        match event.item:
            case AgentRow(agent=agent):
                self.store.selected_id = agent.id

    # --- search & filters --------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one(selector(Id.SEARCH), Input).focus()

    def action_focus_filters(self) -> None:
        self.query_one(selector(Id.FILTERS), FilterChips).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != Id.SEARCH:
            return
        self.store.set_search(event.value)
        self._load_agents()

    def on_filter_chips_changed(self, event: FilterChips.Changed) -> None:
        key = next(iter(event.selected), AgentFilter.ALL.value)
        self.store.select_filter(AgentFilter(key))
        self.mutate_reactive(AgentsScreen.store)

    # --- catalog loading ---------------------------------------------------

    @work(exclusive=True, group="agents-load")
    async def _load_agents(self, *, announce: bool = False) -> None:
        await asyncio.sleep(SEARCH_DEBOUNCE_SECONDS)
        store = self.store
        if store.source is AgentSource.DIRECTORY:
            self.mutate_reactive(AgentsScreen.store)
            return
        store.loading = True
        if announce:
            store.set_status(AgentStatusSource.LIST, REFRESHING_AGENTS_MESSAGE)
            self.mutate_reactive(AgentsScreen.store)
        try:
            agents = await list_managed_agents(
                self.control.client,
                self.control.managed_agents,
                name=store.search or None,
            )
        except Exception as error:
            store.set_status(
                AgentStatusSource.LIST,
                format_platform_error(error, operation="load agents"),
            )
        else:
            store.replace_agents(agents)
            if announce:
                store.set_status(
                    AgentStatusSource.LIST,
                    REFRESHED_AGENTS_MESSAGE.format(count=len(agents)),
                )
            else:
                store.clear_status(AgentStatusSource.LIST)
        finally:
            store.loading = False
            self.mutate_reactive(AgentsScreen.store)

    @work(exclusive=True, group="agents-directory")
    async def _load_directory(self, *, announce: bool = False) -> None:
        store = self.store
        store.loading = True
        if announce:
            store.set_status(AgentStatusSource.LIST, REFRESHING_DIRECTORY_MESSAGE)
            self.mutate_reactive(AgentsScreen.store)
        try:
            directory = await self.control.client.list_directory()
        except Exception as error:
            store.set_status(
                AgentStatusSource.LIST,
                format_platform_error(error, operation="load directory"),
            )
        else:
            store.replace_directory(directory)
            if announce:
                store.set_status(
                    AgentStatusSource.LIST,
                    REFRESHED_DIRECTORY_MESSAGE.format(count=len(directory)),
                )
            else:
                store.clear_status(AgentStatusSource.LIST)
        finally:
            store.loading = False
            self.mutate_reactive(AgentsScreen.store)

    def action_reload(self) -> None:
        self._pending_delete_id = None
        match self.store.source:
            case AgentSource.MINE:
                self._load_agents(announce=True)
            case AgentSource.DIRECTORY:
                self._load_directory(announce=True)

    def _refresh_catalog(self) -> None:
        """Keep the visible platform catalog current without noisy status updates."""
        match self.store.source:
            case AgentSource.MINE:
                self._load_agents()
            case AgentSource.DIRECTORY:
                self._load_directory()

    def action_toggle_discover(self) -> None:
        store = self.store
        store.set_source(
            AgentSource.DIRECTORY
            if store.source is AgentSource.MINE
            else AgentSource.MINE
        )
        self.mutate_reactive(AgentsScreen.store)
        self.action_reload()

    # --- registration ------------------------------------------------------

    def action_new_agent(self) -> None:
        self._pending_delete_id = None
        self.app.push_screen(RegisterAgentScreen())

    def action_reconfigure_agent(self) -> None:
        self._pending_delete_id = None
        agent = self._highlighted_agent()
        if agent is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        self.app.push_screen(RegisterAgentScreen(agent=agent, reconfigure=True))

    def action_open_role_library(self) -> None:
        self._pending_delete_id = None
        try:
            path = open_role_library()
        except OSError as error:
            self._set_status(str(error))
            return
        self._set_status(f"Opened role library at {path}")

    def action_new_role(self) -> None:
        self._pending_delete_id = None
        self.app.push_screen(NewRoleScreen())

    def action_delete_agent(self) -> None:
        agent = self._highlighted_agent()
        if agent is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        if self.store.is_starting(agent.id):
            self._set_status(AGENT_STARTING_MESSAGE)
            return
        if self.store.deleting_ids:
            self._set_status(OPERATION_IN_PROGRESS_MESSAGE)
            return
        if self._pending_delete_id != agent.id:
            self._pending_delete_id = agent.id
            self._set_status(DELETE_CONFIRM_MESSAGE.format(name=agent.name))
            return
        self._pending_delete_id = None
        self.store.begin_delete(agent.id)
        self._set_status(DELETING_AGENT_MESSAGE.format(name=agent.name))
        self._delete_agent(agent)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == Id.SEARCH:
            self.query_one(selector(Id.LIST), ListView).focus()

    # --- start / stop ------------------------------------------------------

    def action_start_agent(self) -> None:
        agent = self._highlighted_agent()
        if agent is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        self.start_managed_agent(agent)

    def action_stop_agent(self) -> None:
        agent = self._highlighted_agent()
        if agent is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        self.stop_managed_agent(agent.id, agent.name)

    def _set_agent_operation_status(self, status: str) -> None:
        self._set_status(status)

    def _refresh_agent_operation_view(self) -> None:
        self.mutate_reactive(AgentsScreen.store)

    @work(exclusive=True, group="agents-delete")
    async def _delete_agent(self, agent: AgentRecord) -> None:
        try:
            await self._stop_agent_for_delete(agent)
            await self.control.client.delete_agent(agent.id)
        except Exception as error:
            if is_missing_resource(error):
                self._remove_agent(agent)
                self._set_status(STALE_AGENT_REMOVED_MESSAGE.format(name=agent.name))
                self._refresh_catalog()
                return
            self._set_status(format_platform_error(error, operation="delete agent"))
            return
        finally:
            self.store.finish_delete(agent.id)
        self._remove_agent(agent)
        self._set_status(f"Deleted {agent.name}.")

    def _remove_agent(self, agent: AgentRecord) -> None:
        self.control.managed_agents.remove(agent.id)
        self.store.remove_agent(agent.id)

    async def _stop_agent_for_delete(self, agent: AgentRecord) -> None:
        worker = await self.control.agent_lifecycle.stop(agent.id)
        if worker is None:
            self.store.mark_stopped(agent.id)
        else:
            self.store.mark_worker(worker)

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(AgentsScreen.store)
