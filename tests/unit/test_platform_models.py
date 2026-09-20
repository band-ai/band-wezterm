"""Platform response mapping stays independent from the client transport."""

from __future__ import annotations

from types import SimpleNamespace

from band_wezterm.identity import AvatarKind
from band_wezterm.platform_models import (
    participant_record_from_api,
    room_record_from_api,
)


def test_room_mapping_uses_the_requested_title_when_api_omits_it() -> None:
    record = room_record_from_api(
        SimpleNamespace(id="room-1", title=None), fallback_title="Planning"
    )

    assert record.id == "room-1"
    assert record.title == "Planning"


def test_participant_mapping_preserves_the_handle_and_agent_kind() -> None:
    record = participant_record_from_api(
        SimpleNamespace(id="agent-1", name="Developer 6753", handle="dev 6753", type="agent")
    )

    assert record.handle == "dev 6753"
    assert record.kind is AvatarKind.AGENT
