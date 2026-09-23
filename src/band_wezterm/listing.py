"""Shared filtering, pagination, and command hints for terminal resource lists."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from band_wezterm.identity import HarnessId

DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100
MIN_PAGE_SIZE: Final = 1


class ResourceKind(StrEnum):
    ROOM = "room"
    AGENT = "agent"


class HarnessFilter(StrEnum):
    CLAUDE = "cl"
    CODEX = "cx"
    COPILOT = "cp"
    OPENCODE = "om"

    @classmethod
    def parse(cls, value: str | None) -> HarnessFilter | None:
        if value is None:
            return None
        try:
            return HARNESS_FILTER_ALIASES[value.casefold()]
        except KeyError as exc:
            choices = ", ".join(filter_.value for filter_ in cls)
            raise ValueError(f"--harness must be one of: {choices}.") from exc


class AgentStateFilter(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

    @classmethod
    def parse(cls, value: str | None) -> AgentStateFilter | None:
        if value is None:
            return None
        try:
            return cls(value.casefold())
        except ValueError as exc:
            choices = ", ".join(state.value for state in cls)
            raise ValueError(f"--state must be one of: {choices}.") from exc


HARNESS_FILTER_ALIASES: Final[dict[str, HarnessFilter]] = {
    HarnessFilter.CLAUDE.value: HarnessFilter.CLAUDE,
    HarnessId.CLAUDE.value: HarnessFilter.CLAUDE,
    HarnessId.CLAUDE_SDK.value: HarnessFilter.CLAUDE,
    HarnessFilter.CODEX.value: HarnessFilter.CODEX,
    HarnessId.CODEX.value: HarnessFilter.CODEX,
    HarnessFilter.COPILOT.value: HarnessFilter.COPILOT,
    HarnessId.COPILOT.value: HarnessFilter.COPILOT,
    HarnessId.COPILOT_SDK.value: HarnessFilter.COPILOT,
    HarnessFilter.OPENCODE.value: HarnessFilter.OPENCODE,
    HarnessId.OMP.value: HarnessFilter.OPENCODE,
    HarnessId.OPENCODE.value: HarnessFilter.OPENCODE,
}


@dataclass(frozen=True)
class ListQuery:
    """A validated terminal-list request."""

    name: str | None = None
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0
    harness: HarnessFilter | None = None
    state: AgentStateFilter | None = None

    def __post_init__(self) -> None:
        if not MIN_PAGE_SIZE <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(
                f"--limit must be between {MIN_PAGE_SIZE} and {MAX_PAGE_SIZE}."
            )
        if self.offset < 0:
            raise ValueError("--offset must be zero or greater.")

    @property
    def is_default(self) -> bool:
        return (
            self.name is None
            and self.limit == DEFAULT_PAGE_SIZE
            and self.offset == 0
            and self.harness is None
            and self.state is None
        )

    def matches_agent(self, *, harness: str | None, state: str) -> bool:
        return (
            (
                self.harness is None
                or _harness_filter(harness) is self.harness
            )
            and (self.state is None or state == self.state.value)
        )


@dataclass(frozen=True)
class PageInfo:
    total: int
    offset: int
    count: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + self.count
        return candidate if candidate < self.total else None


@dataclass(frozen=True)
class ResourcePage[T]:
    items: tuple[T, ...]
    info: PageInfo


def paginate[T](
    items: Sequence[T],
    query: ListQuery,
    *,
    display_name: Callable[[T], str],
    predicate: Callable[[T], bool] | None = None,
) -> ResourcePage[T]:
    """Filter by a case-insensitive name prefix, then select one page."""
    filtered = tuple(
        item
        for item in items
        if query.name is None
        or display_name(item).casefold().startswith(query.name.casefold())
        if predicate is None or predicate(item)
    )
    selected = filtered[query.offset : query.offset + query.limit]
    return ResourcePage(
        items=selected,
        info=PageInfo(total=len(filtered), offset=query.offset, count=len(selected)),
    )


def next_page_command(kind: ResourceKind, query: ListQuery, info: PageInfo) -> str | None:
    """Return a copy-pasteable command for the following page, when present."""
    next_offset = info.next_offset
    if next_offset is None:
        return None
    command = ["band", kind.value, "list"]
    if query.name is not None:
        command.extend(("--name", query.name))
    if query.harness is not None:
        command.extend(("--harness", query.harness.value))
    if query.state is not None:
        command.extend(("--state", query.state.value))
    command.extend(("--limit", str(query.limit), "--offset", str(next_offset)))
    return " ".join(shlex.quote(part) for part in command)


def _harness_filter(harness: str | None) -> HarnessFilter | None:
    return None if harness is None else HARNESS_FILTER_ALIASES.get(harness.casefold())
