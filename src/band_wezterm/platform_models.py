"""Typed platform records and API-to-UI mapping."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from band_wezterm.identity import AvatarKind, HarnessId, agent_accent, initials
from band_wezterm.room_color import room_accent

DEFAULT_MESSAGE_TYPE = "text"


class ParticipantRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class RealtimeEventKind(StrEnum):
    MESSAGE = "message"
    MESSAGE_CREATED = "message_created"
    MESSAGE_UPDATED = "message_updated"
    EVENT_CREATED = "event_created"
    PARTICIPANT_JOINED = "participant_joined"
    PARTICIPANT_LEFT = "participant_left"
    UNKNOWN = "unknown"


class AgentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    kind: AvatarKind
    color: str
    harness: HarnessId | None = None


class RoomRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    color: str


class ParticipantRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    handle: str | None = None
    kind: AvatarKind
    color: str


class MessageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    author_name: str
    inserted_at: datetime | None = None
    message_type: str = DEFAULT_MESSAGE_TYPE
    metadata: Mapping[str, Any] | None = None


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: RealtimeEventKind
    room_id: str | None = None
    payload: Mapping[str, Any] | None = None


class DirectoryEntry(BaseModel):
    """Loose public-directory row — only id/name are required for Discover."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str | None = None
    uuid: str | None = None
    name: str | None = None

    def as_agent(self) -> AgentRecord | None:
        agent_id = self.id or self.uuid
        if not agent_id:
            return None
        return AgentRecord(
            id=str(agent_id),
            name=self.name or str(agent_id),
            kind=AvatarKind.AGENT,
            color=agent_accent(agent_id),
        )


class DirectoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    data: list[DirectoryEntry] = Field(default_factory=list)
    agents: list[DirectoryEntry] = Field(default_factory=list)

    def entries(self) -> list[DirectoryEntry]:
        return self.data or self.agents


_MENTION_MARKUP = re.compile(r"@\[\[([0-9a-fA-F-]+)\]\]")


def display_message_content(
    content: str, metadata: Mapping[str, Any] | None = None
) -> str:
    """Turn platform `@[[uuid]]` mention markup into `@name` for the chat pane."""
    names = {
        str(item["id"]): str(item.get("name") or item.get("handle") or item["id"])
        for item in metadata.get("mentions") or ()
        if isinstance(item, Mapping) and item.get("id") is not None
    } if metadata is not None else {}
    return _MENTION_MARKUP.sub(
        lambda match: f"@{names.get(match.group(1), match.group(1))}", content
    )


def message_record_from_api(message: object) -> MessageRecord:
    """Map a Fern ChatMessage (or compatible object) into the host record."""
    metadata = getattr(message, "metadata", None)
    meta = metadata if isinstance(metadata, Mapping) else None
    raw_type = getattr(message, "message_type", None)
    return MessageRecord(
        id=str(message.id),
        content=display_message_content(
            str(getattr(message, "content", "") or ""),
            meta,
        ),
        author_name=str(
            getattr(message, "sender_name", None)
            or getattr(message, "sender_id", None)
            or "unknown"
        ),
        inserted_at=getattr(message, "inserted_at", None),
        message_type=str(raw_type or DEFAULT_MESSAGE_TYPE),
        metadata=meta,
    )


def agent_record_from_api(
    agent: object, *, fallback_name: str | None = None
) -> AgentRecord:
    agent_id = str(agent.id)
    return AgentRecord(
        id=agent_id,
        name=getattr(agent, "name", None) or fallback_name or agent_id,
        kind=AvatarKind.AGENT,
        color=agent_accent(agent_id),
    )


def room_record_from_api(chat: object, *, fallback_title: str | None = None) -> RoomRecord:
    room_id = str(chat.id)
    return RoomRecord(
        id=room_id,
        title=getattr(chat, "title", None) or fallback_title or room_id,
        color=room_accent(room_id),
    )


def participant_record_from_api(item: object) -> ParticipantRecord:
    participant_id = str(item.id)
    handle = getattr(item, "handle", None)
    kind = getattr(item, "type", None) or getattr(item, "kind", None)
    return ParticipantRecord(
        id=participant_id,
        name=getattr(item, "name", None) or participant_id,
        handle=str(handle) if handle else None,
        kind=AvatarKind.AGENT if str(kind or "").lower() in {"agent", "bot"} else AvatarKind.HUMAN,
        color=agent_accent(participant_id),
    )


def realtime_event_kind(raw: object) -> RealtimeEventKind:
    try:
        return RealtimeEventKind(str(raw))
    except ValueError:
        return RealtimeEventKind.UNKNOWN


def avatar_label(name: str) -> str:
    return initials(name)
