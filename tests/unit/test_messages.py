"""Message history mapping — REST latest page and mention display."""

from __future__ import annotations

from types import SimpleNamespace

from band_wezterm.client import (
    RealtimeEvent,
    RealtimeEventKind,
    display_message_content,
    message_record_from_api,
)
from band_wezterm.tui.screens.rooms import message_from_event


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
    )
    record = message_record_from_api(message)
    assert record.id == "m1"
    assert record.author_name == "user1 ci"
    assert record.content == "@omp hello"


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
        },
    )
    record = message_from_event(event)
    assert record is not None
    assert record.author_name == "omp"
    assert record.content == "pong"
