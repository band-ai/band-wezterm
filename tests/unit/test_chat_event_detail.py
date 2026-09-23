"""Event detail rendering stays consistent with the timeline."""

from __future__ import annotations

from band_wezterm.identity import AvatarKind
from band_wezterm.platform_models import MessageRecord, ParticipantRecord
from band_wezterm.tui.mentions import participant_mention_text
from band_wezterm.tui.screens.chat_event_detail import detail_content


def test_event_detail_reuses_roster_mention_rendering() -> None:
    participant = ParticipantRecord(
        id="architect-1",
        name="Architect",
        handle="architecture",
        kind=AvatarKind.AGENT,
        color="#355dd4",
    )
    message = MessageRecord(
        id="message-1",
        author_name="You",
        content="@architecture review the lifecycle.",
    )

    mention_text = participant_mention_text(message.content, [participant])
    rendered = detail_content(message, message.content, mention_text)

    assert rendered is mention_text
    assert mention_text is not None
    assert mention_text.spans[0].style.color is not None
    assert mention_text.spans[0].style.color.name == participant.color
