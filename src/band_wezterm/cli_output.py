"""Consistent terminal rendering for Band command output."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rich.console import Console
from rich.table import Table

from band_wezterm.listing import ListQuery, PageInfo, ResourceKind, next_page_command


class TableTitle(StrEnum):
    ROOMS = "Rooms"
    AGENTS = "Agents"


class RoomColumn(StrEnum):
    TITLE = "Title"
    ID = "Room ID"


class AgentColumn(StrEnum):
    NAME = "Name"
    STATE = "State"
    ID = "ID"
    HARNESS = "Harness"
    PID = "PID"


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


def print_rooms(
    rows: list[RoomOutput], *, query: ListQuery | None = None, page: PageInfo | None = None
) -> None:
    table = _table(TableTitle.ROOMS)
    table.add_column(RoomColumn.TITLE, no_wrap=True)
    table.add_column(RoomColumn.ID, no_wrap=True)
    for row in rows:
        table.add_row(row.title, row.room_id)
    console = Console()
    console.print(table)
    if query is not None and page is not None:
        _print_page_summary(console, ResourceKind.ROOM, query, page)


def print_agents(
    rows: list[AgentOutput],
    *,
    query: ListQuery,
    page: PageInfo,
    verbose: bool = False,
) -> None:
    console = Console()
    if verbose:
        _print_agent_details(console, rows)
    else:
        table = _table(TableTitle.AGENTS)
        table.add_column(AgentColumn.NAME, no_wrap=True)
        table.add_column(AgentColumn.STATE, no_wrap=True)
        table.add_column(AgentColumn.ID, no_wrap=True)
        for row in rows:
            table.add_row(row.name, row.state, _short_id(row.agent_id))
        console.print(table)
    _print_page_summary(console, ResourceKind.AGENT, query, page)


def print_agent(row: AgentOutput) -> None:
    """Render one lifecycle result with the same contract as ``band agent list``."""
    console = Console()
    _print_agent_details(console, [row])


def _table(title: TableTitle) -> Table:
    return Table(title=title, header_style="bold cyan", expand=False)


def _print_agent_details(console: Console, rows: list[AgentOutput]) -> None:
    console.print(TableTitle.AGENTS)
    for row in rows:
        console.print(
            f"{row.name}\n"
            f"  State: {row.state}\n"
            f"  Agent ID: {row.agent_id}\n"
            f"  Harness: {row.harness or '—'}\n"
            f"  PID: {row.pid if row.pid else '—'}"
        )


def _short_id(agent_id: str) -> str:
    return agent_id.split("-", maxsplit=1)[0]


def _print_page_summary(
    console: Console, kind: ResourceKind, query: ListQuery, page: PageInfo
) -> None:
    if page.total == 0:
        console.print(f"No {kind.value}s match the requested filters.")
        return
    if page.count == 0:
        console.print(f"No {kind.value}s at offset {page.offset}; {page.total} match.")
        return
    first = page.offset + 1
    last = page.offset + page.count
    console.print(f"Showing {first}-{last} of {page.total} {kind.value}s.")
    if command := next_page_command(kind, query, page):
        console.print(f"Next: {command}")
