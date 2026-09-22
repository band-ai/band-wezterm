"""Room roster ordering — me → humans → local agents → outside."""

from __future__ import annotations

from band_wezterm.identity import AvatarKind
from band_wezterm.platform_models import ParticipantRecord
from band_wezterm.tui.roster_order import RosterGroup, order_roster, roster_group

ME_ID = "user-me"
HUMAN_A_ID = "user-alice"
HUMAN_B_ID = "user-bob"
LOCAL_DEV_ID = "agent-dev"
LOCAL_PM_ID = "agent-pm"
OUTSIDE_QQQ_ID = "agent-qqq"
OUTSIDE_AAAAA_ID = "agent-aaaaa"


def _participant(
    participant_id: str,
    name: str,
    *,
    kind: AvatarKind,
) -> ParticipantRecord:
    return ParticipantRecord(
        id=participant_id,
        name=name,
        handle=name,
        kind=kind,
        color="#7ee787",
    )


def test_roster_group_classifies_me_humans_local_outside() -> None:
    local = frozenset({LOCAL_DEV_ID, LOCAL_PM_ID})
    me = _participant(ME_ID, "me", kind=AvatarKind.HUMAN)
    human = _participant(HUMAN_A_ID, "alice", kind=AvatarKind.HUMAN)
    local_agent = _participant(LOCAL_DEV_ID, "Developer", kind=AvatarKind.AGENT)
    outside = _participant(OUTSIDE_QQQ_ID, "qqq", kind=AvatarKind.AGENT)

    assert (
        roster_group(me, user_id=ME_ID, local_agent_ids=local) is RosterGroup.SELF
    )
    assert (
        roster_group(human, user_id=ME_ID, local_agent_ids=local)
        is RosterGroup.HUMAN
    )
    assert (
        roster_group(local_agent, user_id=ME_ID, local_agent_ids=local)
        is RosterGroup.LOCAL
    )
    assert (
        roster_group(outside, user_id=ME_ID, local_agent_ids=local)
        is RosterGroup.OUTSIDE
    )


def test_order_roster_matches_vscode_groups_then_alpha() -> None:
    """Parity with VS Code INT-1521 — screenshot-style mixed API order."""
    unordered = [
        _participant(LOCAL_DEV_ID, "Developer jkgjly openai", kind=AvatarKind.AGENT),
        _participant(HUMAN_A_ID, "user1 ci", kind=AvatarKind.HUMAN),
        _participant(LOCAL_PM_ID, "Product Manager hql5sv", kind=AvatarKind.AGENT),
        _participant(OUTSIDE_QQQ_ID, "qqq", kind=AvatarKind.AGENT),
        _participant(OUTSIDE_AAAAA_ID, "aaaaa", kind=AvatarKind.AGENT),
        _participant(ME_ID, "zaikman", kind=AvatarKind.HUMAN),
        _participant(HUMAN_B_ID, "bob", kind=AvatarKind.HUMAN),
    ]

    ordered = order_roster(
        unordered,
        user_id=ME_ID,
        local_agent_ids={LOCAL_DEV_ID, LOCAL_PM_ID},
    )

    assert [participant.id for participant in ordered] == [
        ME_ID,
        HUMAN_B_ID,
        HUMAN_A_ID,
        LOCAL_DEV_ID,
        LOCAL_PM_ID,
        OUTSIDE_AAAAA_ID,
        OUTSIDE_QQQ_ID,
    ]


def test_order_roster_without_user_id_keeps_humans_ahead_of_agents() -> None:
    unordered = [
        _participant(OUTSIDE_QQQ_ID, "qqq", kind=AvatarKind.AGENT),
        _participant(HUMAN_A_ID, "alice", kind=AvatarKind.HUMAN),
        _participant(LOCAL_DEV_ID, "Developer", kind=AvatarKind.AGENT),
    ]

    ordered = order_roster(
        unordered,
        user_id=None,
        local_agent_ids={LOCAL_DEV_ID},
    )

    assert [participant.id for participant in ordered] == [
        HUMAN_A_ID,
        LOCAL_DEV_ID,
        OUTSIDE_QQQ_ID,
    ]
