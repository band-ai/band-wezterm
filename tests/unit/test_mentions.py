"""Composer mention parsing and completion."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from band_wezterm.client import ParticipantRecord
from band_wezterm.identity import AvatarKind
from band_wezterm.tui.screens.rooms import resolve_mention
from band_wezterm.tui.widgets import MarkdownComposer, MentionSuggester

PARTICIPANT_ID = "0f5d0b7c-1a3e-4c5b-9d2f-6a7b8c9d0e1f"
HANDLE_WITH_SPACES = "Developer 6753"


class ComposerApp(App[None]):
    def compose(self) -> ComposeResult:
        yield MarkdownComposer(id="composer")


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


@pytest.mark.asyncio
async def test_tab_accepts_the_inline_handle_completion() -> None:
    async with ComposerApp().run_test() as pilot:
        composer = pilot.app.query_one(MarkdownComposer)
        composer.set_mention_handles((HANDLE_WITH_SPACES,))
        composer.focus()
        composer.value = "@dev"
        await pilot.pause()

        await pilot.press("tab")

        assert composer.value == "@[Developer 6753] "
