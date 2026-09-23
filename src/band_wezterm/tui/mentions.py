"""Participant-handle presentation shared by Band text surfaces."""

from __future__ import annotations

import re
from collections.abc import Iterable

from rich.style import Style
from rich.text import Text

from band_wezterm.platform_models import ParticipantRecord


def mention_keys(participant: ParticipantRecord) -> tuple[str, ...]:
    """Return accepted handles, preferring the platform's canonical handle."""
    keys = (participant.handle, participant.name)
    return tuple(dict.fromkeys(key for key in keys if key))


def participant_mention_text(
    content: str, participants: Iterable[ParticipantRecord]
) -> Text | None:
    """Color unambiguous ``@mentions`` with their roster identity color."""
    matches = sorted(
        (
            (key, participant.color)
            for participant in participants
            for key in mention_keys(participant)
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    rendered = Text(content)
    styled = False
    for key, color in matches:
        for match in re.finditer(rf"(?<!\S)@{re.escape(key)}(?=\s|$)", content, re.I):
            rendered.stylize(Style(color=color, bold=True), *match.span())
            styled = True
    return rendered if styled else None
