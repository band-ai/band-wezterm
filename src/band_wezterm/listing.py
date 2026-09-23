"""Shared filtering, pagination, and command hints for terminal resource lists."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100
MIN_PAGE_SIZE: Final = 1


class ResourceKind(StrEnum):
    ROOM = "room"
    AGENT = "agent"


@dataclass(frozen=True)
class ListQuery:
    """A validated terminal-list request."""

    name: str | None = None
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    def __post_init__(self) -> None:
        if not MIN_PAGE_SIZE <= self.limit <= MAX_PAGE_SIZE:
            raise ValueError(
                f"--limit must be between {MIN_PAGE_SIZE} and {MAX_PAGE_SIZE}."
            )
        if self.offset < 0:
            raise ValueError("--offset must be zero or greater.")

    @property
    def is_default(self) -> bool:
        return self.name is None and self.limit == DEFAULT_PAGE_SIZE and self.offset == 0


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
    items: Sequence[T], query: ListQuery, *, display_name: Callable[[T], str]
) -> ResourcePage[T]:
    """Filter by a case-insensitive name prefix, then select one page."""
    filtered = tuple(
        item
        for item in items
        if query.name is None
        or display_name(item).casefold().startswith(query.name.casefold())
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
    command.extend(("--limit", str(query.limit), "--offset", str(next_offset)))
    return " ".join(shlex.quote(part) for part in command)
