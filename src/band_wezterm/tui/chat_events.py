"""Chat timeline event taxonomy — filter categories, preview, visibility."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Final

from band_wezterm.platform_models import DEFAULT_MESSAGE_TYPE, MessageRecord

EVENT_PREVIEW_MAX_LENGTH: Final = 100
EMPTY_EVENT_PREVIEW: Final = "(no additional details)"
FILTERED_EMPTY_CHAT: Final = (
    "All messages are hidden by the current event type filter."
)
DISCLOSURE_COLLAPSED: Final = "▸"
DISCLOSURE_EXPANDED: Final = "▾"


class EventFilterCategory(StrEnum):
    TEXT = "text"
    THOUGHT = "thought"
    TASK = "task"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    ATTENTION = "attention"
    SYSTEM = "system"


CATEGORY_LABELS: Final[dict[EventFilterCategory, str]] = {
    EventFilterCategory.TEXT: "Messages",
    EventFilterCategory.THOUGHT: "Thoughts",
    EventFilterCategory.TASK: "Tasks",
    EventFilterCategory.TOOL_CALL: "Tool Calls",
    EventFilterCategory.TOOL_RESULT: "Tool Results",
    EventFilterCategory.ERROR: "Errors",
    EventFilterCategory.ATTENTION: "Attention",
    EventFilterCategory.SYSTEM: "System",
}

BADGE_LABELS: Final[dict[str, str]] = {
    EventFilterCategory.TEXT.value: "Messages",
    EventFilterCategory.THOUGHT.value: "Thought",
    EventFilterCategory.TASK.value: "Task",
    EventFilterCategory.TOOL_CALL.value: "Tool Call",
    EventFilterCategory.TOOL_RESULT.value: "Tool Result",
    EventFilterCategory.ERROR.value: "Errors",
    EventFilterCategory.ATTENTION.value: "Attention",
    EventFilterCategory.SYSTEM.value: "System",
    "participant": "Participant",
}

CATEGORY_WIRE_TYPES: Final[dict[EventFilterCategory, frozenset[str]]] = {
    EventFilterCategory.TEXT: frozenset({EventFilterCategory.TEXT.value}),
    EventFilterCategory.THOUGHT: frozenset({EventFilterCategory.THOUGHT.value}),
    EventFilterCategory.TASK: frozenset({EventFilterCategory.TASK.value}),
    EventFilterCategory.TOOL_CALL: frozenset({EventFilterCategory.TOOL_CALL.value}),
    EventFilterCategory.TOOL_RESULT: frozenset(
        {EventFilterCategory.TOOL_RESULT.value}
    ),
    EventFilterCategory.ERROR: frozenset({EventFilterCategory.ERROR.value}),
    EventFilterCategory.ATTENTION: frozenset({EventFilterCategory.ATTENTION.value}),
    EventFilterCategory.SYSTEM: frozenset(
        {EventFilterCategory.SYSTEM.value, "participant"}
    ),
}

ALL_FILTERABLE_TYPES: Final[frozenset[str]] = frozenset().union(
    *CATEGORY_WIRE_TYPES.values()
)

DEFAULT_ALLOWED_TYPES: Final[tuple[str, ...]] = (
    EventFilterCategory.TEXT.value,
    EventFilterCategory.THOUGHT.value,
    EventFilterCategory.SYSTEM.value,
    "participant",
)

VERBOSE_TYPES: Final[frozenset[str]] = frozenset(
    {
        EventFilterCategory.TASK.value,
        EventFilterCategory.TOOL_CALL.value,
        EventFilterCategory.TOOL_RESULT.value,
        EventFilterCategory.ERROR.value,
        EventFilterCategory.ATTENTION.value,
    }
)

ALWAYS_EXPANDED_TYPES: Final[frozenset[str]] = frozenset(
    {
        EventFilterCategory.TEXT.value,
        EventFilterCategory.ERROR.value,
        EventFilterCategory.THOUGHT.value,
    }
)

CATEGORY_ORDER: Final[tuple[EventFilterCategory, ...]] = tuple(EventFilterCategory)


def badge_label(message_type: str) -> str:
    return BADGE_LABELS.get(message_type, message_type)


def is_filterable(message_type: str) -> bool:
    return message_type in ALL_FILTERABLE_TYPES


def is_always_expanded(message_type: str) -> bool:
    return message_type in ALWAYS_EXPANDED_TYPES


def category_selected(
    category: EventFilterCategory, allowed: Iterable[str]
) -> bool:
    allowed_set = frozenset(allowed)
    return CATEGORY_WIRE_TYPES[category] <= allowed_set


def toggle_category(
    category: EventFilterCategory, allowed: Sequence[str]
) -> tuple[str, ...]:
    """Flip every wire type in the category; return a new allow-list tuple."""
    current = set(allowed)
    wires = CATEGORY_WIRE_TYPES[category]
    if wires <= current:
        current -= wires
    else:
        current |= wires
    return normalize_allowed_types(current)


def select_all_categories(allowed: Sequence[str]) -> tuple[str, ...]:
    """Turn every visible category on, retaining unknown persisted types."""
    retained = {item for item in allowed if item not in ALL_FILTERABLE_TYPES}
    return normalize_allowed_types(retained | set(ALL_FILTERABLE_TYPES))


def clear_all_categories(allowed: Sequence[str]) -> tuple[str, ...]:
    """Turn every visible category off, retaining unknown persisted types."""
    retained = {item for item in allowed if item not in ALL_FILTERABLE_TYPES}
    return normalize_allowed_types(retained)


def all_categories_selected(allowed: Iterable[str]) -> bool:
    return frozenset(allowed) >= ALL_FILTERABLE_TYPES


def normalize_allowed_types(allowed: Iterable[str]) -> tuple[str, ...]:
    allowed_set = {str(item) for item in allowed}
    ordered: list[str] = []
    seen: set[str] = set()
    for category in CATEGORY_ORDER:
        for wire in sorted(CATEGORY_WIRE_TYPES[category]):
            if wire in allowed_set and wire not in seen:
                ordered.append(wire)
                seen.add(wire)
    for wire in sorted(allowed_set):
        if wire not in seen:
            ordered.append(wire)
            seen.add(wire)
    return tuple(ordered)


def message_is_visible(message: MessageRecord, allowed: Iterable[str]) -> bool:
    message_type = message.message_type or DEFAULT_MESSAGE_TYPE
    if not is_filterable(message_type):
        return True
    return message_type in frozenset(allowed)


def visible_messages(
    messages: Sequence[MessageRecord], allowed: Iterable[str]
) -> list[MessageRecord]:
    return [message for message in messages if message_is_visible(message, allowed)]


def count_by_category(
    messages: Sequence[MessageRecord],
) -> dict[EventFilterCategory, int]:
    counts = dict.fromkeys(CATEGORY_ORDER, 0)
    for message in messages:
        message_type = message.message_type or DEFAULT_MESSAGE_TYPE
        for category, wires in CATEGORY_WIRE_TYPES.items():
            if message_type in wires:
                counts[category] += 1
                break
    return counts


def hidden_summary(
    messages: Sequence[MessageRecord], allowed: Iterable[str]
) -> str:
    allowed_set = frozenset(allowed)
    hidden_counts: dict[EventFilterCategory, int] = {}
    for message in messages:
        message_type = message.message_type or DEFAULT_MESSAGE_TYPE
        if not is_filterable(message_type) or message_type in allowed_set:
            continue
        for category, wires in CATEGORY_WIRE_TYPES.items():
            if message_type in wires:
                hidden_counts[category] = hidden_counts.get(category, 0) + 1
                break
    if not hidden_counts:
        return ""
    parts = [
        f"{count} {CATEGORY_LABELS[category].lower()}"
        for category, count in (
            (cat, hidden_counts[cat])
            for cat in CATEGORY_ORDER
            if cat in hidden_counts
        )
    ]
    return f"Hidden: {', '.join(parts)}"


def apply_verbose(
    allowed: Sequence[str], *, enabled: bool, previous: Sequence[str] | None
) -> tuple[str, ...]:
    if enabled:
        return normalize_allowed_types(set(allowed) | VERBOSE_TYPES)
    if previous is None:
        return normalize_allowed_types(set(allowed) - VERBOSE_TYPES)
    return normalize_allowed_types(previous)


def verbose_active(allowed: Iterable[str]) -> bool:
    return frozenset(allowed) >= VERBOSE_TYPES


def event_preview(content: str) -> str:
    trimmed = content.strip()
    if not trimmed:
        return EMPTY_EVENT_PREVIEW
    first_line = trimmed.split("\n", 1)[0]
    characters = list(first_line)
    if len(characters) <= EVENT_PREVIEW_MAX_LENGTH:
        return first_line
    return "".join(characters[:EVENT_PREVIEW_MAX_LENGTH]) + "…"


def error_display_content(
    content: str, metadata: Mapping[str, Any] | None
) -> str:
    if metadata is None:
        return content
    failure = metadata.get("failure")
    if not isinstance(failure, Mapping):
        return content
    provider = failure.get("provider")
    if not provider:
        return content
    return f"[{provider}] {content}"


def metadata_pretty(metadata: Mapping[str, Any] | None) -> str | None:
    if not metadata:
        return None
    try:
        return json.dumps(dict(metadata), indent=2, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def content_pretty(content: str) -> str:
    """Pretty-print JSON content when possible; otherwise return the raw string."""
    trimmed = content.strip()
    if not trimmed:
        return content
    try:
        parsed = json.loads(trimmed)
    except (TypeError, ValueError, json.JSONDecodeError):
        return content
    try:
        return json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return content
