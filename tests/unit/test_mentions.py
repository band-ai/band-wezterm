"""Composer mention parsing and completion."""

from __future__ import annotations

import pytest

from band_wezterm.client import ParticipantRecord
from band_wezterm.identity import AvatarKind
from band_wezterm.tui.screens.rooms import resolve_mention
from band_wezterm.tui.widgets import MentionSuggester

PARTICIPANT_ID = "0f5d0b7c-1a3e-4c5b-9d2f-6a7b8c9d0e1f"
HANDLE_WITH_SPACES = "Developer 6753"


def participant() -> ParticipantRecord:
    return ParticipantRecord(
        id=PARTICIPANT_ID,
        name="Developer",
        handle=HANDLE_WITH_SPACES,
        kind=AvatarKind.AGENT,
        color="#7ee787",
    )


def test_resolve_mention_keeps_handle_with_spaces_together() -> None:
    recipient = participant()

    resolved = resolve_mention("@[Developer 6753] hello", [recipient])

    assert resolved == (recipient, "hello")


def test_resolve_mention_rejects_a_partial_multiword_handle() -> None:
    assert resolve_mention("@Developer 6753 hello", [participant()]) is None


@pytest.mark.asyncio
async def test_mention_suggester_completes_a_multiword_handle() -> None:
    suggestion = await MentionSuggester(lambda: (HANDLE_WITH_SPACES,)).get_suggestion(
        "hello @dev"
    )

    assert suggestion == "hello @[Developer 6753] "
