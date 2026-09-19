"""RoomsStore filter chips are exclusive; All shows every room."""

from __future__ import annotations

from band_wezterm.client import RoomRecord
from band_wezterm.tui.stores import RoomFilter, RoomsStore


def _room(room_id: str, title: str) -> RoomRecord:
    return RoomRecord(id=room_id, title=title, color="#355dd4")


def test_all_shows_starred_and_unstarred() -> None:
    store = RoomsStore(
        rooms=[_room("1", "Alpha"), _room("2", "Beta")],
        starred_ids=frozenset({"1"}),
        filter=RoomFilter.ALL,
    )
    assert [room.title for room in store.visible] == ["Alpha", "Beta"]


def test_starred_filter_hides_unstarred() -> None:
    store = RoomsStore(
        rooms=[_room("1", "Alpha"), _room("2", "Beta")],
        starred_ids=frozenset({"1"}),
    )
    store.select_filter(RoomFilter.STARRED)
    assert [room.title for room in store.visible] == ["Alpha"]
    store.select_filter(RoomFilter.ALL)
    assert [room.title for room in store.visible] == ["Alpha", "Beta"]


def test_remove_room_clears_selection_and_star() -> None:
    store = RoomsStore(
        rooms=[_room("1", "Alpha"), _room("2", "Beta")],
        starred_ids=frozenset({"1", "2"}),
        selected_id="1",
    )
    store.remove_room("1")
    assert [room.id for room in store.rooms] == ["2"]
    assert store.selected_id is None
    assert store.starred_ids == frozenset({"2"})
