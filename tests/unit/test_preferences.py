"""Host preferences store."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from band_wezterm.preferences import HostPreferences, PreferencesStore


def test_preferences_round_trip(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "prefs.json")
    store.update(
        rooms_page_size=40,
        chat_messages_limit=50,
        diagnostic_log=False,
        interactive_agent_console=True,
    )
    reloaded = PreferencesStore(tmp_path / "prefs.json")
    assert reloaded.current.rooms_page_size == 40
    assert reloaded.current.chat_messages_limit == 50
    assert reloaded.current.diagnostic_log is False
    assert reloaded.current.interactive_agent_console is True


def test_preferences_interactive_agent_console_defaults_off() -> None:
    assert HostPreferences().interactive_agent_console is False


def test_preferences_reject_out_of_range() -> None:
    with pytest.raises(ValidationError):
        HostPreferences(rooms_page_size=2)


def test_preferences_chat_event_types_round_trip(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "prefs.json")
    store.update(chat_event_types=("text", "tool_call"))
    reloaded = PreferencesStore(tmp_path / "prefs.json")
    assert "tool_call" in reloaded.current.chat_event_types
    assert "text" in reloaded.current.chat_event_types
