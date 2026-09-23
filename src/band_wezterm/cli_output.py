"""Consistent terminal rendering for Band command output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from rich.console import Console
from rich.table import Table


class TableTitle(StrEnum):
    ROOMS = "Rooms"
    AGENTS = "Agents"


class RoomColumn(StrEnum):
    TITLE = "Title"
    ID = "Room ID"
    ACTION = "Action"


class AgentColumn(StrEnum):
    NAME = "Name"
    STATE = "State"
    ID = "Agent ID"
    HARNESS = "Harness"
    PID = "PID"


ROOM_COMMAND_HINT: Final = "Run: band room open ROOM_ID"


@dataclass(frozen=True)
class RoomOutput:
    title: str
    room_id: str


@dataclass(frozen=True)
class AgentOutput:
    name: str
    state: str
    agent_id: str
    harness: str | None = None
    pid: int | None = None


def print_rooms(rows: list[RoomOutput]) -> None:
    table = _table(TableTitle.ROOMS)
    table.add_column(RoomColumn.TITLE, no_wrap=True)
    table.add_column(RoomColumn.ID, no_wrap=True)
    table.add_column(RoomColumn.ACTION, no_wrap=True)
    for row in rows:
        table.add_row(row.title, row.room_id, "open")
    console = Console()
    console.print(table)
    console.print(ROOM_COMMAND_HINT)


def print_agents(rows: list[AgentOutput], *, verbose: bool = False) -> None:
    table = _table(TableTitle.AGENTS)
    table.add_column(AgentColumn.NAME, no_wrap=True)
    table.add_column(AgentColumn.STATE, no_wrap=True)
    table.add_column(AgentColumn.ID, no_wrap=True)
    if verbose:
        table.add_column(AgentColumn.HARNESS, no_wrap=True)
        table.add_column(AgentColumn.PID, no_wrap=True)
    for row in rows:
        values = [row.name, row.state, row.agent_id]
        if verbose:
            values.extend((row.harness or "—", str(row.pid) if row.pid else "—"))
        table.add_row(*values)
    console = Console()
    console.print(table)


def print_agent(row: AgentOutput) -> None:
    """Render one lifecycle result with the same contract as ``band agent list``."""
    print_agents([row], verbose=True)


def _table(title: TableTitle) -> Table:
    return Table(title=title, header_style="bold cyan", expand=True)
