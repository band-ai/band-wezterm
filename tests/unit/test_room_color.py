"""Unit tests for room accent colors."""

from __future__ import annotations

from band_wezterm.identity import agent_accent
from band_wezterm.room_color import ROOM_HUES, room_accent


def test_room_accent_deterministic() -> None:
    room_id = "cccccccccccccccc-cccc-cccc-cccc-cccccccccccc"
    assert room_accent(room_id) == room_accent(room_id)
    assert room_accent(room_id).startswith("#")


def test_room_accent_differs_from_agent_accent_algorithm() -> None:
    shared = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    # Distinct algorithms/palettes — must not silently share the agent path.
    assert room_accent(shared) != agent_accent(shared)


def test_room_accent_distinguishes_ids() -> None:
    assert room_accent("room-a") != room_accent("room-b")


def _sample_ids(count: int = 500) -> list[str]:
    return [f"00000000-0000-0000-0000-{index:012d}" for index in range(count)]


def test_room_palette_is_bounded_by_its_hue_grid() -> None:
    palette = {room_accent(room_id) for room_id in _sample_ids()}
    assert 1 < len(palette) <= len(ROOM_HUES)


def test_room_and_agent_palettes_never_collide() -> None:
    """Same id in both palettes is not enough — no room color may be an agent color."""
    ids = _sample_ids()
    rooms = {room_accent(room_id) for room_id in ids}
    agents = {agent_accent(agent_id) for agent_id in ids}
    assert rooms.isdisjoint(agents)
