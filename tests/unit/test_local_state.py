"""Unit tests for starred-rooms local state."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.local_state import StarredRooms


def test_star_unstar_toggle_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = StarredRooms(path)
    user = "user-1"
    room = "room-1"
    assert not store.is_starred(user, room)
    store.star(user, room)
    assert store.is_starred(user, room)
    reloaded = StarredRooms(path)
    assert reloaded.is_starred(user, room)
    assert reloaded.toggle(user, room) is False
    assert not StarredRooms(path).is_starred(user, room)
    assert reloaded.toggle(user, room) is True
    reloaded.unstar(user, room)
    assert StarredRooms(path).list(user) == frozenset()


def test_stars_are_scoped_per_user(tmp_path: Path) -> None:
    store = StarredRooms(tmp_path / "state.json")
    store.star("user-1", "room-1")
    assert store.list("user-1") == frozenset({"room-1"})
    assert store.list("user-2") == frozenset()
    store.unstar("user-2", "room-1")
    assert store.is_starred("user-1", "room-1")
