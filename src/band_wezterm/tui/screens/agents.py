"""Agents catalog — search, filter chips, registration, start/stop, discover."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Final

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from band_wezterm.agent.adapters import HarnessUnavailableError
from band_wezterm.agent.launch import (
    AgentLaunchContext,
    AgentLaunchResources,
    prepare_agent_launch,
    rollback_agent_launch,
    spawn_agent_panes,
)
from band_wezterm.agent.native_console import NativeConsoleUnavailableError
from band_wezterm.agent.readiness import preflight_managed_agent
from band_wezterm.client import AgentRecord
from band_wezterm.errors import format_platform_error, is_missing_resource
from band_wezterm.identity import AgentRuntime, HarnessBadge, harness_badge
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.role_library import open_role_library
from band_wezterm.tui.refresh import CATALOG_POLL_SECONDS
from band_wezterm.tui.screens import ControlScreen
from band_wezterm.tui.screens.new_role import NewRoleScreen
from band_wezterm.tui.screens.register_agent import RegisterAgentScreen
from band_wezterm.tui.stores import (
    AGENT_FILTER_LABELS,
    AgentFilter,
    AgentPanes,
    AgentSource,
    AgentsStore,
    AgentStatusSource,
)
from band_wezterm.tui.widgets import AvatarChip, Chip, FilterChips
from band_wezterm.wezterm_cli import (
    WezTermCliError,
    kill_panes,
    list_panes,
)

NO_BADGE: Final = "  "

PANE_POLL_SECONDS: Final = 2.0
SEARCH_DEBOUNCE_SECONDS: Final = 0.25

SEARCH_PLACEHOLDER: Final = "Search agents by name"
SOURCE_LABELS: Final[dict[AgentSource, str]] = {
    AgentSource.MINE: "My agents",
    AgentSource.DIRECTORY: "Discover · public directory",
}
EMPTY_CATALOG: Final = "No agents match the current search and filter."
NO_WINDOW_MESSAGE: Final = "No WezTerm window — start the host with `band-wezterm`."
NO_SELECTION_MESSAGE: Final = "Select an agent first."
NO_MANAGED_KEY_MESSAGE: Final = (
    "No managed API key for this agent — re-register it from Control "
    "(keys are one-time at registration)."
)
DELETE_CONFIRM_MESSAGE: Final = (
    "Press Delete again to permanently remove {name}."
)
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
NO_MANAGED_PROFILE_MESSAGE: Final = (
    "No local profile — register or reconfigure after upgrade."
)
AGENT_STARTING_MESSAGE: Final = "Agent is starting; wait for it to finish before deleting it."
STARTING_AGENT_MESSAGE: Final = "Starting {name}…"
PANE_CLEANUP_FAILED_MESSAGE: Final = (
    "Agent start failed and its panes could not be closed; use Stop to retry cleanup."
)
PREFLIGHT_HARNESS_STABILITY_ATTEMPTS: Final = 5
PROFILE_HARNESS_UNSTABLE_MESSAGE: Final = (
    "Harness kept changing during preflight — try Start again."
)
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
        self, agent: AgentRecord, *, running: bool, deleting: bool = False
    ) -> None:
        super().__init__()
        self.agent = agent
        self.running = running
        self.deleting = deleting

    def compose(self) -> ComposeResult:
        yield AvatarChip(self.agent)
        yield Label(self.agent.name, classes="row-name")
        yield Label(badge_label(self.agent), classes="row-badge")
        yield Label(
            (
                DELETING_LABEL
                if self.deleting
                else (AgentRuntime.RUNNING if self.running else AgentRuntime.IDLE).value
            ),
            classes="row-state",
        )


class AgentsScreen(ControlScreen):
    """Keyboard-first agents catalog projected from ``AgentsStore``."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+a", "app.show_agents", "Agents", show=False),
        Binding("ctrl+o", "app.show_rooms", "Rooms", show=False),
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

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._starting_agent_ids: set[str] = set()

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
        self.set_interval(PANE_POLL_SECONDS, self._reconcile_panes)
        self.set_interval(CATALOG_POLL_SECONDS, self._refresh_catalog)
        self._load_agents()

    def on_screen_resume(self) -> None:
        """Return focus to the catalog after an overlay closes."""
        if not self.is_mounted:
            return
        self.query_one(selector(Id.LIST), ListView).focus()
        self._refresh_catalog()

    async def watch_store(self, store: AgentsStore) -> None:
        if not self.is_mounted:
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
        return row.agent if isinstance(row, AgentRow) else None

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, AgentRow):
            self.store.selected_id = event.item.agent.id

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
            agents = await self.control.client.list_my_agents(name=store.search or None)
        except Exception as error:
            store.set_status(
                AgentStatusSource.LIST,
                format_platform_error(error, operation="load agents"),
            )
        else:
            profiles = self.control.managed_agents
            projected: list[AgentRecord] = []
            for agent in agents:
                harness = profiles.harness_for(agent.id)
                row = (
                    agent.model_copy(update={"harness": harness})
                    if harness is not None and harness is not agent.harness
                    else agent
                )
                projected.append(row)
            store.replace_agents(projected)
            if announce:
                store.set_status(
                    AgentStatusSource.LIST,
                    REFRESHED_AGENTS_MESSAGE.format(count=len(projected)),
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
        if agent.id in self._starting_agent_ids:
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
        if self.control.window_id is None:
            self._set_status(NO_WINDOW_MESSAGE)
            return
        if self.store.is_running(agent.id):
            return
        if agent.id in self._starting_agent_ids:
            return
        self._starting_agent_ids.add(agent.id)
        self._set_status(STARTING_AGENT_MESSAGE.format(name=agent.name))
        self._start_agent(agent)

    def action_stop_agent(self) -> None:
        agent = self._highlighted_agent()
        if agent is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        panes = self.store.running.get(agent.id)
        if panes is None:
            return
        self._stop_agent(agent.id, agent.name, panes)

    def _sync_agent_to_profile(
        self, agent: AgentRecord, profile: ManagedAgentProfile
    ) -> AgentRecord:
        if agent.harness is profile.harness:
            return agent
        updated = agent.model_copy(update={"harness": profile.harness})
        self.store.update_agent(updated)
        return updated

    def _resync_store_to_durable_profile(self, agent: AgentRecord) -> None:
        current = self.control.managed_agents.get(agent.id)
        if current is None:
            return
        self._sync_agent_to_profile(agent, current)
        self.mutate_reactive(AgentsScreen.store)

    async def _preflight_launch_profile(
        self, agent_id: str, profile: ManagedAgentProfile
    ) -> ManagedAgentProfile | None:
        """Mid-flight reconfigure can change harness between check and return."""
        current = profile
        for _ in range(PREFLIGHT_HARNESS_STABILITY_ATTEMPTS):
            preflighted = current.harness
            try:
                await asyncio.to_thread(preflight_managed_agent, preflighted)
            except (HarnessUnavailableError, NativeConsoleUnavailableError) as error:
                self._set_status(str(error))
                return None
            fresh = self.control.managed_agents.get(agent_id)
            if fresh is None:
                self._set_status(NO_MANAGED_PROFILE_MESSAGE)
                return None
            if fresh.harness is preflighted:
                return fresh
            current = fresh
        self._set_status(PROFILE_HARNESS_UNSTABLE_MESSAGE)
        return None

    async def _resolve_launch_context(
        self, agent: AgentRecord
    ) -> AgentLaunchContext | None:
        """Validate and stabilize the durable inputs used by one agent launch."""
        window_id = self.control.window_id
        api_key = self.control.client.managed_agent_api_key(agent.id)
        profile = self.control.managed_agents.get(agent.id)
        match window_id, api_key, profile:
            case None, _, _:
                self._set_status(NO_WINDOW_MESSAGE)
                return None
            case _, None | "", _:
                self._set_status(NO_MANAGED_KEY_MESSAGE)
                return None
            case _, _, None:
                self._set_status(NO_MANAGED_PROFILE_MESSAGE)
                return None
            case window_id, api_key, profile:
                agent = self._sync_agent_to_profile(agent, profile)

        preflighted = await self._preflight_launch_profile(agent.id, profile)
        if preflighted is None:
            self._resync_store_to_durable_profile(agent)
            return None
        fresh = self.control.managed_agents.get(agent.id)
        match fresh:
            case None:
                self._set_status(NO_MANAGED_PROFILE_MESSAGE)
                return None
            case fresh if fresh.harness is not preflighted.harness:
                self._sync_agent_to_profile(agent, fresh)
                self._set_status(PROFILE_HARNESS_UNSTABLE_MESSAGE)
                return None
            case fresh:
                return AgentLaunchContext(
                    agent=self._sync_agent_to_profile(agent, fresh),
                    api_key=api_key,
                    profile=fresh,
                    window_id=window_id,
                    cwd=Path.cwd(),
                )

    @work(group="agents-start")
    async def _start_agent(self, agent: AgentRecord) -> None:
        resources: AgentLaunchResources | None = None
        committed = False
        try:
            context = await self._resolve_launch_context(agent)
            if context is None:
                return
            agent = context.agent
            if self.store.is_running(agent.id):
                return
            resources = prepare_agent_launch(context)
            panes = await spawn_agent_panes(context, resources)
            self.store.mark_running(agent.id, panes.bridge, console=panes.console)
            committed = True
            self.store.status = (
                f"Started {agent.name} ({context.profile.harness.value}) "
                "with private console and Band bridge."
            )
            self.mutate_reactive(AgentsScreen.store)
        except Exception as error:
            self._set_status(format_platform_error(error, operation="start agent"))
        finally:
            self._starting_agent_ids.discard(agent.id)
            if resources is not None and not committed:
                panes = await rollback_agent_launch(resources)
                if panes is not None:
                    self.store.mark_running(agent.id, panes.bridge, console=panes.console)
                    self._set_status(PANE_CLEANUP_FAILED_MESSAGE)

    @work(exclusive=True, group="agents-stop")
    async def _stop_agent(
        self, agent_id: str, agent_name: str, panes: AgentPanes
    ) -> None:
        try:
            await asyncio.to_thread(kill_panes, panes.ids)
        except (WezTermCliError, OSError) as error:
            self._set_status(format_platform_error(error, operation="stop agent"))
            return
        self.store.mark_stopped(agent_id)
        self._set_status(f"Stopped {agent_name}.")
        self.mutate_reactive(AgentsScreen.store)

    @work(exclusive=True, group="agents-panes")
    async def _reconcile_panes(self) -> None:
        """Closing either half of an agent tab stops its private console and bridge."""
        store = self.store
        if not store.running:
            return
        try:
            panes = await asyncio.to_thread(list_panes)
        except (WezTermCliError, OSError) as error:
            self._set_status(format_platform_error(error, operation="reconcile agent panes"))
            return
        live_pane_ids = {pane.pane_id for pane in panes}
        incomplete = store.agents_with_missing_panes(live_pane_ids)
        stopped_count = 0
        for agent_id, agent_panes in incomplete:
            survivors = tuple(
                pane_id
                for pane_id in agent_panes.ids
                if pane_id.root in live_pane_ids
            )
            try:
                await asyncio.to_thread(kill_panes, survivors)
            except (WezTermCliError, OSError) as error:
                self._set_status(format_platform_error(error, operation="reconcile agent panes"))
                continue
            store.mark_stopped(agent_id)
            stopped_count += 1
        if stopped_count:
            self._set_status(f"{stopped_count} agent tab(s) closed — marked stopped.")

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
        panes = self.store.running.get(agent.id)
        if panes is None:
            return
        await asyncio.to_thread(kill_panes, panes.ids)
        self.store.mark_stopped(agent.id)

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(AgentsScreen.store)
