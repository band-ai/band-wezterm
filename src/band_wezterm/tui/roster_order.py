"""Room roster ordering — me, humans, local agents, outside agents."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from band_wezterm.identity import AvatarKind
from band_wezterm.platform_models import ParticipantRecord


class RosterGroup(StrEnum):
    SELF = "self"
    HUMAN = "human"
    LOCAL = "local"
    OUTSIDE = "outside"


_ROSTER_GROUP_RANK: dict[RosterGroup, int] = {
    RosterGroup.SELF: 0,
    RosterGroup.HUMAN: 1,
    RosterGroup.LOCAL: 2,
    RosterGroup.OUTSIDE: 3,
}


def roster_group(
    participant: ParticipantRecord,
    *,
    user_id: str | None,
    local_agent_ids: Iterable[str],
) -> RosterGroup:
    """Classify one roster row — mirrors VS Code INT-1521 avatar groups."""
    if user_id is not None and participant.id == user_id:
        return RosterGroup.SELF
    if participant.kind is AvatarKind.HUMAN:
        return RosterGroup.HUMAN
    local = frozenset(local_agent_ids)
    if participant.id in local:
        return RosterGroup.LOCAL
    return RosterGroup.OUTSIDE


def order_roster(
    participants: Sequence[ParticipantRecord],
    *,
    user_id: str | None,
    local_agent_ids: Iterable[str],
) -> list[ParticipantRecord]:
    """Stable display order: me → humans → local agents → outside agents."""
    local = frozenset(local_agent_ids)
    return sorted(
        participants,
        key=lambda participant: (
            _ROSTER_GROUP_RANK[
                roster_group(
                    participant, user_id=user_id, local_agent_ids=local
                )
            ],
            participant.name.casefold(),
            participant.id,
        ),
    )
