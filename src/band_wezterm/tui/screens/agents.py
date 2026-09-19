"""Agents catalog — search, filter chips, registration, start/stop, discover."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Final

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from band_wezterm.client import AgentRecord
from band_wezterm.identity import (
    AgentRuntime,
    AgentStatus,
    HarnessBadge,
    harness_badge,
    initials,
)
from band_wezterm.osc import OscKey, emit_many
from band_wezterm.tui.screens import ControlScreen
from band_wezterm.tui.stores import (
    AGENT_FILTER_LABELS,
    AgentFilter,
    AgentSource,
    AgentsStore,
)
from band_wezterm.tui.widgets import AvatarChip, Chip, FilterChips
from band_wezterm.wezterm_cli import (
    PaneId,
    WezTermCliError,
    kill_pane,
    list_panes,
    set_tab_title,
    spawn_additional_tab,
)

NO_BADGE: Final = "  "

# PoC placeholder process — launching a real harness lands in a later slice.
# `cat` copies pane input to output so OSC SetUserVar from send-text is parsed
# (WezTerm has no cli inject-output; sleep would ignore input).
AGENT_POC_COMMAND: Final[list[str]] = [
    "bash",
    "-lc",
    "echo agent; exec cat",
]
PANE_POLL_SECONDS: Final = 2.0
SEARCH_DEBOUNCE_SECONDS: Final = 0.25

SEARCH_PLACEHOLDER: Final = "Search agents by name"
DRAFT_NAME_PLACEHOLDER: Final = "Agent name"
DRAFT_DESCRIPTION_PLACEHOLDER: Final = "What this agent does"
DRAFT_TITLE: Final = "Register agent — registration only, no tab is spawned"
SOURCE_LABELS: Final[dict[AgentSource, str]] = {
    AgentSource.MINE: "My agents",
    AgentSource.DIRECTORY: "Discover · public directory",
}
EMPTY_CATALOG: Final = "No agents match the current search and filter."
NO_WINDOW_MESSAGE: Final = "No WezTerm window — start the host with `band-wezterm`."
NO_SELECTION_MESSAGE: Final = "Select an agent first."
DRAFT_INCOMPLETE_MESSAGE: Final = "Name and description are both required."


class Id(StrEnum):
    """Widget ids owned by this screen."""

    SEARCH = "agent-search"
    FILTERS = "agent-filters"
    SOURCE = "agent-source"
    LIST = "agent-list"
    DRAFT = "agent-draft"
    DRAFT_NAME = "agent-draft-name"
    DRAFT_DESCRIPTION = "agent-draft-description"
    STATUS = "agent-status"
    TOOLBAR = "agent-toolbar"


OPEN_CLASS: Final = "open"

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


def announce_agent(pane_id: PaneId, agent: AgentRecord) -> None:
    """Publish the agent's display identity into its own pane as user-vars."""
    fields: dict[OscKey, str] = {
        OscKey.AGENT_ID: agent.id,
        OscKey.AGENT_NAME: agent.name,
        OscKey.AGENT_INITIALS: initials(agent.name),
        OscKey.AGENT_COLOR: agent.color,
        OscKey.AGENT_KIND: agent.kind.value,
        OscKey.AGENT_STATUS: AgentStatus.ONLINE.value,
        OscKey.AGENT_RUNTIME: AgentRuntime.RUNNING.value,
    }
    badge = badge_for(agent)
    if badge is not None:
        fields[OscKey.AGENT_HARNESS] = badge.value
    emit_many(pane_id, fields)
    set_tab_title(pane_id, agent.name)


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

    def __init__(self, agent: AgentRecord, *, running: bool) -> None:
        super().__init__()
        self.agent = agent
        self.running = running

    def compose(self) -> ComposeResult:
        yield AvatarChip(self.agent)
        yield Label(self.agent.name, classes="row-name")
        yield Label(badge_label(self.agent), classes="row-badge")
        yield Label(
            (AgentRuntime.RUNNING if self.running else AgentRuntime.IDLE).value,
            classes="row-state",
        )


class AgentsScreen(ControlScreen):
    """Keyboard-first agents catalog projected from ``AgentsStore``."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("slash", "focus_search", "Search"),
        Binding("f", "focus_filters", "Filters"),
        Binding("n", "new_agent", "Register"),
        Binding("s", "start_agent", "Start"),
        Binding("x", "stop_agent", "Stop"),
        Binding("d", "toggle_discover", "Discover"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    AgentsScreen #agent-toolbar {
        height: 3;
    }
    AgentsScreen #agent-source {
        width: 28;
        content-align: right middle;
    }
    AgentsScreen #agent-draft {
        display: none;
        height: auto;
        border: round $accent;
        padding: 0 1;
    }
    AgentsScreen #agent-draft.open {
        display: block;
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
        with Vertical(id=Id.DRAFT.value):
            yield Static(DRAFT_TITLE)
            yield Input(placeholder=DRAFT_NAME_PLACEHOLDER, id=Id.DRAFT_NAME.value)
            yield Input(
                placeholder=DRAFT_DESCRIPTION_PLACEHOLDER,
                id=Id.DRAFT_DESCRIPTION.value,
            )
        yield Static("", id=Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self.store = self.control.agents_store
        self.query_one(selector(Id.LIST), ListView).focus()
        self.set_interval(PANE_POLL_SECONDS, self._reconcile_panes)
        self._load_agents()

    def on_screen_resume(self) -> None:
        """A draft never survives leaving the screen — reopen it from scratch."""
        self._close_draft()

    async def watch_store(self, store: AgentsStore) -> None:
        if not self.is_mounted:
            return
        self.query_one(selector(Id.SOURCE), Static).update(SOURCE_LABELS[store.source])
        self.query_one(selector(Id.DRAFT), Vertical).set_class(
            store.draft_open, OPEN_CLASS
        )
        await self._render_rows(store)

    async def _render_rows(self, store: AgentsStore) -> None:
        visible = store.visible
        list_view = self.query_one(selector(Id.LIST), ListView)
        await list_view.clear()
        await list_view.extend(
            AgentRow(agent, running=store.is_running(agent.id)) for agent in visible
        )
        list_view.index = next(
            (
                index
                for index, agent in enumerate(visible)
                if agent.id == store.selected_id
            ),
            0 if visible else None,
        )
        self.query_one(selector(Id.STATUS), Static).update(
            store.status or ("" if visible else EMPTY_CATALOG)
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
        self.store.search = event.value
        self._load_agents()

    def on_filter_chips_changed(self, event: FilterChips.Changed) -> None:
        key = next(iter(event.selected), AgentFilter.ALL.value)
        self.store.select_filter(AgentFilter(key))
        self.mutate_reactive(AgentsScreen.store)

    # --- catalog loading ---------------------------------------------------

    @work(exclusive=True, group="agents-load")
    async def _load_agents(self) -> None:
        await asyncio.sleep(SEARCH_DEBOUNCE_SECONDS)
        store = self.store
        if store.source is AgentSource.DIRECTORY:
            self.mutate_reactive(AgentsScreen.store)
            return
        store.loading = True
        try:
            agents = await self.control.client.list_my_agents(name=store.search or None)
        except Exception as error:
            store.status = str(error)
        else:
            store.replace_agents(agents)
            store.status = ""
        finally:
            store.loading = False
            self.mutate_reactive(AgentsScreen.store)

    @work(exclusive=True, group="agents-directory")
    async def _load_directory(self) -> None:
        store = self.store
        store.loading = True
        try:
            directory = await self.control.client.list_directory()
        except Exception as error:
            store.status = str(error)
        else:
            store.replace_directory(directory)
            store.status = ""
        finally:
            store.loading = False
            self.mutate_reactive(AgentsScreen.store)

    def action_reload(self) -> None:
        match self.store.source:
            case AgentSource.MINE:
                self._load_agents()
            case AgentSource.DIRECTORY:
                self._load_directory()

    def action_toggle_discover(self) -> None:
        store = self.store
        store.source = (
            AgentSource.DIRECTORY
            if store.source is AgentSource.MINE
            else AgentSource.MINE
        )
        self.mutate_reactive(AgentsScreen.store)
        if store.source is AgentSource.DIRECTORY:
            self._load_directory()

    # --- registration draft (transient overlay) ----------------------------

    def action_new_agent(self) -> None:
        self.store.draft_open = True
        self.mutate_reactive(AgentsScreen.store)
        self.query_one(selector(Id.DRAFT_NAME), Input).focus()

    def action_cancel(self) -> None:
        if self.store.draft_open:
            self._close_draft()
            return
        self.query_one(selector(Id.LIST), ListView).focus()

    def _close_draft(self) -> None:
        self.store.discard_draft()
        self.query_one(selector(Id.DRAFT_NAME), Input).value = ""
        self.query_one(selector(Id.DRAFT_DESCRIPTION), Input).value = ""
        self.mutate_reactive(AgentsScreen.store)
        self.query_one(selector(Id.LIST), ListView).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        match event.input.id:
            case Id.DRAFT_NAME:
                self.query_one(selector(Id.DRAFT_DESCRIPTION), Input).focus()
            case Id.DRAFT_DESCRIPTION:
                self._submit_draft()
            case Id.SEARCH:
                self.query_one(selector(Id.LIST), ListView).focus()

    def _submit_draft(self) -> None:
        name = self.query_one(selector(Id.DRAFT_NAME), Input).value.strip()
        description = self.query_one(selector(Id.DRAFT_DESCRIPTION), Input).value.strip()
        if not name or not description:
            self._set_status(DRAFT_INCOMPLETE_MESSAGE)
            return
        self._register_agent(name, description)

    @work(exclusive=True, group="agents-register")
    async def _register_agent(self, name: str, description: str) -> None:
        store = self.store
        try:
            agent = await self.control.client.create_agent(
                name=name, description=description
            )
        except Exception as error:
            self._set_status(str(error))
            return
        store.add_agent(agent)
        store.status = f"Registered {agent.name} — not started."
        self._close_draft()

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
        self._start_agent(agent)

    def action_stop_agent(self) -> None:
        agent = self._highlighted_agent()
        if agent is None:
            self._set_status(NO_SELECTION_MESSAGE)
            return
        pane_id = self.store.running.get(agent.id)
        if pane_id is None:
            return
        self._stop_agent(agent.id, agent.name, pane_id)

    @work(group="agents-spawn")
    async def _start_agent(self, agent: AgentRecord) -> None:
        window_id = self.control.window_id
        if window_id is None:
            self._set_status(NO_WINDOW_MESSAGE)
            return
        store = self.store
        pane_id: PaneId | None = None
        try:
            pane_id = await asyncio.to_thread(
                spawn_additional_tab, window_id, Path.cwd(), AGENT_POC_COMMAND
            )
            await asyncio.to_thread(announce_agent, pane_id, agent)
        except (WezTermCliError, OSError) as error:
            if pane_id is not None:
                with suppress(WezTermCliError, OSError):
                    await asyncio.to_thread(kill_pane, pane_id)
            self._set_status(str(error))
            return
        store.mark_running(agent.id, pane_id)
        store.status = (f"Started {agent.name} in pane {pane_id.root} — PoC tab only; harness reply is not wired yet.")
        self.mutate_reactive(AgentsScreen.store)

    @work(group="agents-spawn")
    async def _stop_agent(
        self, agent_id: str, agent_name: str, pane_id: PaneId
    ) -> None:
        try:
            await asyncio.to_thread(kill_pane, pane_id)
        except (WezTermCliError, OSError) as error:
            self._set_status(str(error))
            return
        self.store.mark_stopped(agent_id)
        self._set_status(f"Stopped {agent_name}.")
        self.mutate_reactive(AgentsScreen.store)

    @work(exclusive=True, group="agents-panes")
    async def _reconcile_panes(self) -> None:
        """A closed agent tab is a stop — reconcile against the live panes."""
        store = self.store
        if not store.running:
            return
        try:
            panes = await asyncio.to_thread(list_panes)
        except (WezTermCliError, OSError):
            return
        stopped = store.prune_running(pane.pane_id for pane in panes)
        if stopped:
            self._set_status(f"{len(stopped)} agent tab(s) closed — marked stopped.")

    def _set_status(self, status: str) -> None:
        self.store.status = status
        self.mutate_reactive(AgentsScreen.store)
