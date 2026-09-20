"""Screen state holders — mutable dataclasses watched through Textual reactives.

Screens mutate a store and call ``mutate_reactive`` so ``compose``/``watch``
stay a pure projection of the store.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from band_wezterm.client import (
    AgentRecord,
    MessageRecord,
    ParticipantRecord,
    RoomRecord,
)
from band_wezterm.identity import HARNESS_BADGES, HarnessBadge
from band_wezterm.wezterm_cli import PaneId


class AgentSource(StrEnum):
    """Which catalog the Agents screen is currently projecting."""

    MINE = "mine"
    DIRECTORY = "directory"


class AgentFilter(StrEnum):
    ALL = "all"
    RUNNING = "running"
    IDLE = "idle"
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    OPENCODE = "opencode"


class RoomFilter(StrEnum):
    ALL = "all"
    STARRED = "starred"


class RoomStatusSource(StrEnum):
    """Independent asynchronous operations that can report room feedback."""

    ACTION = "action"
    LIST = "list"
    ROSTER = "roster"
    MESSAGES = "messages"
    PARTICIPANTS = "participants"
    REALTIME = "realtime"


AgentPredicate = Callable[[AgentRecord, frozenset[str]], bool]


def _badge_is(badge: HarnessBadge) -> AgentPredicate:
    return lambda agent, _running: (
        agent.harness is not None and HARNESS_BADGES.get(agent.harness) == badge
    )


AGENT_FILTERS: Final[dict[AgentFilter, AgentPredicate]] = {
    AgentFilter.RUNNING: lambda agent, running: agent.id in running,
    AgentFilter.IDLE: lambda agent, running: agent.id not in running,
    AgentFilter.CLAUDE: _badge_is(HarnessBadge.CL),
    AgentFilter.CODEX: _badge_is(HarnessBadge.CX),
    AgentFilter.COPILOT: _badge_is(HarnessBadge.CP),
    AgentFilter.OPENCODE: _badge_is(HarnessBadge.OM),
}

AGENT_FILTER_LABELS: Final[dict[AgentFilter, str]] = {
    AgentFilter.ALL: "All",
    AgentFilter.RUNNING: "Running",
    AgentFilter.IDLE: "Idle",
    AgentFilter.CLAUDE: "Claude",
    AgentFilter.CODEX: "Codex",
    AgentFilter.COPILOT: "Copilot",
    AgentFilter.OPENCODE: "OpenCode",
}

ROOM_FILTER_LABELS: Final[dict[RoomFilter, str]] = {
    RoomFilter.ALL: "All",
    RoomFilter.STARRED: "Starred",
}


def _matches_search(haystack: str, needle: str) -> bool:
    return needle.strip().lower() in haystack.lower()


@dataclass(frozen=True)
class AgentPanes:
    """The private console and Band bridge that form one managed agent tab."""

    console: PaneId
    bridge: PaneId

    @property
    def ids(self) -> tuple[PaneId, ...]:
        if self.console == self.bridge:
            return (self.console,)
        return (self.console, self.bridge)


@dataclass
class AgentsStore:
    """Agents catalog: search, one exclusive chip (All = no filter), run state."""

    agents: list[AgentRecord] = field(default_factory=list)
    directory: list[AgentRecord] = field(default_factory=list)
    source: AgentSource = AgentSource.MINE
    search: str = ""
    filter: AgentFilter = AgentFilter.ALL
    running: dict[str, AgentPanes] = field(default_factory=dict)
    selected_id: str | None = None
    loading: bool = False
    status: str = ""

    @property
    def catalog(self) -> list[AgentRecord]:
        return (
            self.agents if self.source is AgentSource.MINE else self.directory
        )

    @property
    def running_ids(self) -> frozenset[str]:
        return frozenset(self.running)

    @property
    def visible(self) -> list[AgentRecord]:
        """Search plus at most one chip; ``All`` leaves the catalog unfiltered."""
        running = self.running_ids
        chip = self.filter
        return [
            agent
            for agent in self.catalog
            if _matches_search(agent.name, self.search)
            and (
                chip is AgentFilter.ALL
                or AGENT_FILTERS[chip](agent, running)
            )
        ]

    def find(self, agent_id: str) -> AgentRecord | None:
        return next(
            (agent for agent in self.catalog if agent.id == agent_id), None
        )

    def replace_agents(self, agents: Sequence[AgentRecord]) -> None:
        self.agents = list(agents)

    def replace_directory(self, agents: Sequence[AgentRecord]) -> None:
        self.directory = list(agents)

    def add_agent(self, agent: AgentRecord) -> None:
        self.agents = [agent, *self.agents]
        self.selected_id = agent.id

    def update_agent(self, agent: AgentRecord) -> None:
        self.agents = [
            agent if existing.id == agent.id else existing for existing in self.agents
        ]

    def remove_agent(self, agent_id: str) -> None:
        self.agents = [agent for agent in self.agents if agent.id != agent_id]
        self.mark_stopped(agent_id)
        if self.selected_id == agent_id:
            self.selected_id = self.agents[0].id if self.agents else None

    def select_filter(self, chip: AgentFilter) -> None:
        self.filter = chip

    def is_running(self, agent_id: str) -> bool:
        return agent_id in self.running

    def mark_running(
        self,
        agent_id: str,
        bridge: PaneId,
        *,
        console: PaneId | None = None,
    ) -> None:
        self.running[agent_id] = AgentPanes(console=console or bridge, bridge=bridge)

    def mark_stopped(self, agent_id: str) -> AgentPanes | None:
        return self.running.pop(agent_id, None)

    def prune_running(self, live_pane_ids: Iterable[int]) -> list[str]:
        """Drop agents whose tab was closed — closing an agent tab is a stop."""
        live = set(live_pane_ids)
        stopped = [
            agent_id
            for agent_id, panes in self.running.items()
            if any(pane.root not in live for pane in panes.ids)
        ]
        for agent_id in stopped:
            del self.running[agent_id]
        return stopped

@dataclass
class RoomsStore:
    """Rooms list plus the detail (roster, picker, chat) of the selected room."""

    rooms: list[RoomRecord] = field(default_factory=list)
    search: str = ""
    filter: RoomFilter = RoomFilter.ALL
    starred_ids: frozenset[str] = frozenset()
    selected_id: str | None = None
    draft_open: bool = False
    participants: list[ParticipantRecord] = field(default_factory=list)
    candidates: list[AgentRecord] = field(default_factory=list)
    picker_open: bool = False
    _messages: dict[str, MessageRecord] = field(default_factory=dict)
    loading: bool = False
    _status_by_source: dict[RoomStatusSource, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """Most recent live feedback; one operation cannot erase another's error."""
        return next(reversed(self._status_by_source.values()), "")

    @status.setter
    def status(self, message: str) -> None:
        self.set_status(RoomStatusSource.ACTION, message)

    def set_status(self, source: RoomStatusSource, message: str) -> None:
        self._status_by_source.pop(source, None)
        if message:
            self._status_by_source[source] = message

    def clear_status(self, source: RoomStatusSource) -> None:
        self._status_by_source.pop(source, None)

    def clear_detail_statuses(self) -> None:
        for source in RoomStatusSource:
            if source is not RoomStatusSource.LIST:
                self._status_by_source.pop(source, None)

    @property
    def messages(self) -> list[MessageRecord]:
        return list(self._messages.values())

    @property
    def visible(self) -> list[RoomRecord]:
        """Search plus at most one chip; ``All`` leaves starring as decoration only."""
        return [
            room
            for room in self.rooms
            if _matches_search(room.title, self.search)
            and (
                self.filter is RoomFilter.ALL
                or room.id in self.starred_ids
            )
        ]

    @property
    def participant_ids(self) -> frozenset[str]:
        return frozenset(participant.id for participant in self.participants)

    def find(self, room_id: str) -> RoomRecord | None:
        return next((room for room in self.rooms if room.id == room_id), None)

    def replace_rooms(self, rooms: Sequence[RoomRecord]) -> None:
        self.rooms = list(rooms)

    def add_room(self, room: RoomRecord) -> None:
        self.rooms = [room, *self.rooms]
        self.selected_id = room.id

    def remove_room(self, room_id: str) -> None:
        self.rooms = [room for room in self.rooms if room.id != room_id]
        if self.selected_id == room_id:
            self.selected_id = None
            self.participants = []
            self.candidates = []
            self._messages = {}
            self.picker_open = False
        self.starred_ids = frozenset(
            sid for sid in self.starred_ids if sid != room_id
        )

    def select_filter(self, chip: RoomFilter) -> None:
        self.filter = chip

    def is_starred(self, room_id: str) -> bool:
        return room_id in self.starred_ids

    def enter_room(self, room_id: str) -> None:
        """Reset the detail projection — roster/chat belong to one room only."""
        self.selected_id = room_id
        self.participants = []
        self.candidates = []
        self._messages = {}
        self.picker_open = False
        self.clear_detail_statuses()

    def replace_participants(
        self, participants: Sequence[ParticipantRecord]
    ) -> None:
        self.participants = list(participants)

    def replace_messages(self, messages: Sequence[MessageRecord]) -> None:
        """Replace the open room's history (REST latest page, oldest-first)."""
        self._messages = {message.id: message for message in messages}

    def addable_candidates(self) -> list[AgentRecord]:
        """Add-only picker: agents already in the roster are never offered."""
        present = self.participant_ids
        return [
            agent for agent in self.candidates if agent.id not in present
        ]

    def remove_participant(self, participant_id: str) -> None:
        self.participants = [
            participant
            for participant in self.participants
            if participant.id != participant_id
        ]

    def append_message(self, message: MessageRecord) -> None:
        """Insert or replace by id (plugin upsertMessage — covers message_updated)."""
        self._messages[message.id] = message

    def find_participant(self, participant_id: str) -> ParticipantRecord | None:
        return next(
            (
                participant
                for participant in self.participants
                if participant.id == participant_id
            ),
            None,
        )

    def discard_draft(self) -> None:
        self.draft_open = False
        self.picker_open = False
