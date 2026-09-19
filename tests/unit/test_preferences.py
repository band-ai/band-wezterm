"""Host preferences store."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from band_wezterm.preferences import HostPreferences, PreferencesStore


def test_preferences_round_trip(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "prefs.json")
    store.update(rooms_page_size=40, chat_messages_limit=50, diagnostic_log=False)
    reloaded = PreferencesStore(tmp_path / "prefs.json")
    assert reloaded.current.rooms_page_size == 40
    assert reloaded.current.chat_messages_limit == 50
    assert reloaded.current.diagnostic_log is False


def test_preferences_reject_out_of_range() -> None:
    with pytest.raises(ValidationError):
        HostPreferences(rooms_page_size=2)
