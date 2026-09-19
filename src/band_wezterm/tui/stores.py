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
    RUNNING = "running"
    IDLE = "idle"
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    OPENCODE = "opencode"


class RoomFilter(StrEnum):
    STARRED = "starred"


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
    AgentFilter.RUNNING: "Running",
    AgentFilter.IDLE: "Idle",
    AgentFilter.CLAUDE: "Claude",
    AgentFilter.CODEX: "Codex",
    AgentFilter.COPILOT: "Copilot",
    AgentFilter.OPENCODE: "OpenCode",
}

ROOM_FILTER_LABELS: Final[dict[RoomFilter, str]] = {RoomFilter.STARRED: "Starred"}


def _matches_search(haystack: str, needle: str) -> bool:
    return needle.strip().lower() in haystack.lower()


@dataclass
class AgentsStore:
    """Agents catalog: search, AND-combined chips, run state and draft form."""

    agents: list[AgentRecord] = field(default_factory=list)
    directory: list[AgentRecord] = field(default_factory=list)
    source: AgentSource = AgentSource.MINE
    search: str = ""
    filters: frozenset[AgentFilter] = frozenset()
    running: dict[str, PaneId] = field(default_factory=dict)
    selected_id: str | None = None
    draft_open: bool = False
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
        """Search AND every selected chip — chips never widen the result set."""
        running = self.running_ids
        return [
            agent
            for agent in self.catalog
            if _matches_search(agent.name, self.search)
            and all(
                AGENT_FILTERS[chip](agent, running) for chip in self.filters
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

    def toggle_filter(self, chip: AgentFilter) -> None:
        self.filters = self.filters ^ {chip}

    def is_running(self, agent_id: str) -> bool:
        return agent_id in self.running

    def mark_running(self, agent_id: str, pane_id: PaneId) -> None:
        self.running[agent_id] = pane_id

    def mark_stopped(self, agent_id: str) -> PaneId | None:
        return self.running.pop(agent_id, None)

    def prune_running(self, live_pane_ids: Iterable[int]) -> list[str]:
        """Drop agents whose tab was closed — closing an agent tab is a stop."""
        live = set(live_pane_ids)
        stopped = [
            agent_id
            for agent_id, pane_id in self.running.items()
            if pane_id.root not in live
        ]
        for agent_id in stopped:
            del self.running[agent_id]
        return stopped

    def discard_draft(self) -> None:
        self.draft_open = False


@dataclass
class RoomsStore:
    """Rooms list plus the detail (roster, picker, chat) of the selected room."""

    rooms: list[RoomRecord] = field(default_factory=list)
    search: str = ""
    filters: frozenset[RoomFilter] = frozenset()
    starred_ids: frozenset[str] = frozenset()
    selected_id: str | None = None
    draft_open: bool = False
    participants: list[ParticipantRecord] = field(default_factory=list)
    candidates: list[AgentRecord] = field(default_factory=list)
    picker_open: bool = False
    _messages: dict[str, MessageRecord] = field(default_factory=dict)
    loading: bool = False
    status: str = ""

    @property
    def messages(self) -> list[MessageRecord]:
        return list(self._messages.values())

    @property
    def visible(self) -> list[RoomRecord]:
        return [
            room
            for room in self.rooms
            if _matches_search(room.title, self.search)
            and (
                RoomFilter.STARRED not in self.filters
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

    def toggle_filter(self, chip: RoomFilter) -> None:
        self.filters = self.filters ^ {chip}

    def is_starred(self, room_id: str) -> bool:
        return room_id in self.starred_ids

    def enter_room(self, room_id: str) -> None:
        """Reset the detail projection — roster/chat belong to one room only."""
        self.selected_id = room_id
        self.participants = []
        self.candidates = []
        self._messages = {}
        self.picker_open = False

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
