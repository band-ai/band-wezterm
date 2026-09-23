"""RoomsStore filter chips are exclusive; All shows every room."""

from __future__ import annotations

from datetime import UTC, datetime

from band_wezterm.client import MessageRecord, RoomRecord
from band_wezterm.tui.stores import RoomFilter, RoomsStore, RoomStatusSource


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


def test_successful_history_load_cannot_clear_realtime_failure() -> None:
    store = RoomsStore()
    store.set_status(RoomStatusSource.REALTIME, "Realtime connection failed")
    store.clear_status(RoomStatusSource.MESSAGES)

    assert store.status == "Realtime connection failed"


def test_entering_another_room_clears_old_detail_failure() -> None:
    store = RoomsStore()
    store.set_status(RoomStatusSource.REALTIME, "Realtime connection failed")
    store.set_status(RoomStatusSource.LIST, "Room list unavailable")

    store.enter_room("room-2")

    assert store.status == "Room list unavailable"


def test_messages_are_ordered_by_platform_timestamp() -> None:
    store = RoomsStore()
    later = MessageRecord(
        id="later",
        content="later",
        author_name="Agent",
        inserted_at=datetime(2026, 9, 23, 8, 1, tzinfo=UTC),
    )
    earlier = MessageRecord(
        id="earlier",
        content="earlier",
        author_name="Agent",
        inserted_at=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
    )

    store.replace_messages([later, earlier])

    assert [message.id for message in store.messages] == ["earlier", "later"]
