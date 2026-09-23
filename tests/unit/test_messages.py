"""Message history mapping — REST latest page and mention display."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from band_wezterm.client import (
    BandClient,
    RealtimeEvent,
    RealtimeEventKind,
    display_message_content,
    message_record_from_api,
)
from band_wezterm.tui.screens.rooms import message_from_event, message_time_label


def test_display_message_content_resolves_mention_markup() -> None:
    content = "@[[cedab9da-f8c3-472b-9b4b-090f2e9afcf7]] hey"
    rendered = display_message_content(
        content,
        {
            "mentions": [
                {
                    "id": "cedab9da-f8c3-472b-9b4b-090f2e9afcf7",
                    "name": "copilot",
                }
            ]
        },
    )
    assert rendered == "@copilot hey"


def test_message_record_from_api_oldest_fields() -> None:
    message = SimpleNamespace(
        id="m1",
        content="@[[aaaa]] hello",
        sender_name="user1 ci",
        sender_id="u1",
        metadata={"mentions": [{"id": "aaaa", "name": "omp"}]},
        inserted_at=datetime(2026, 9, 23, 7, 53, tzinfo=UTC),
        message_type="text",
    )
    record = message_record_from_api(message)
    assert record.id == "m1"
    assert record.author_name == "user1 ci"
    assert record.author_id == "u1"
    assert record.content == "@omp hello"
    assert record.message_type == "text"
    assert record.metadata == {"mentions": [{"id": "aaaa", "name": "omp"}]}
    assert record.inserted_at == datetime(2026, 9, 23, 7, 53, tzinfo=UTC)


def test_message_record_from_api_keeps_tool_type() -> None:
    message = SimpleNamespace(
        id="m2",
        content="ToolSearch",
        sender_name="Architect",
        sender_id="a1",
        metadata={"tool": "search"},
        message_type="tool_call",
    )
    record = message_record_from_api(message)
    assert record.message_type == "tool_call"
    assert record.metadata == {"tool": "search"}


def test_message_time_label_includes_seconds() -> None:
    record = message_record_from_api(
        SimpleNamespace(
            id="m3",
            content="hello",
            sender_name="Architect",
            sender_id="a1",
            metadata=None,
            message_type="text",
            inserted_at=datetime(2026, 9, 23, 7, 53, 42, tzinfo=UTC),
        )
    )

    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", message_time_label(record))


def test_message_from_event_ignores_participant_left() -> None:
    event = RealtimeEvent(
        kind=RealtimeEventKind.PARTICIPANT_LEFT,
        room_id="r1",
        payload={"content": "omp left the conversation", "id": "e1"},
    )
    assert message_from_event(event) is None


def test_message_from_event_maps_sender_name() -> None:
    event = RealtimeEvent(
        kind=RealtimeEventKind.MESSAGE_CREATED,
        room_id="r1",
        payload={
            "id": "m2",
            "content": "pong",
            "sender_name": "omp",
            "inserted_at": "2026-09-23T07:53:00Z",
        },
    )
    record = message_from_event(event)
    assert record is not None
    assert record.author_name == "omp"
    assert record.author_id is None
    assert record.content == "pong"
    assert record.message_type == "text"
    assert record.inserted_at == datetime(2026, 9, 23, 7, 53, tzinfo=UTC)


def test_message_from_event_created_maps_type_and_empty_content() -> None:
    event = RealtimeEvent(
        kind=RealtimeEventKind.EVENT_CREATED,
        room_id="r1",
        payload={
            "id": "e1",
            "content": "",
            "message_type": "tool_call",
            "sender_name": "Architect",
            "metadata": {"name": "ToolSearch"},
        },
    )
    record = message_from_event(event)
    assert record is not None
    assert record.message_type == "tool_call"
    assert record.content == ""
    assert record.metadata == {"name": "ToolSearch"}


@pytest.mark.asyncio
async def test_send_message_builds_row_from_request_not_empty_ack() -> None:
    """MessageSentResponse is delivery-only; the timeline row uses the request."""
    client = BandClient.__new__(BandClient)
    ack = SimpleNamespace(id="msg-42", recipients=[], success=True)
    client._messages = MagicMock()
    client._messages.send_my_chat_message = AsyncMock(
        return_value=SimpleNamespace(data=ack)
    )

    record = await BandClient.send_message(
        client,
        "room-1",
        "Hello team",
        mentions=[("a1", "aaaaa"), ("q1", "qqq")],
        sender_name="user1 ci",
    )
    assert record.id == "msg-42"
    assert record.author_name == "user1 ci"
    assert record.content == "@aaaaa @qqq Hello team"
    assert record.message_type == "text"
    assert record.metadata == {
        "mentions": [
            {"id": "a1", "name": "aaaaa"},
            {"id": "q1", "name": "qqq"},
        ]
    }
