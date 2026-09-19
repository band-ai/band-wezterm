"""Unit tests for identity visuals."""

from __future__ import annotations

from uuid import UUID

import pytest

from band_wezterm.identity import (
    HARNESS_BADGES,
    HarnessBadge,
    HarnessId,
    agent_accent,
    harness_badge,
    initials,
)


def test_agent_accent_deterministic() -> None:
    agent_id = UUID("11111111-1111-1111-1111-111111111111")
    assert agent_accent(agent_id) == agent_accent(agent_id)
    assert agent_accent(agent_id).startswith("#")
    assert len(agent_accent(agent_id)) == 7


def test_agent_accent_distinguishes_ids() -> None:
    a = agent_accent("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    b = agent_accent("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    assert a != b


def test_initials_rules() -> None:
    assert initials("") == "?"
    assert initials("   ") == "?"
    assert initials("Ada") == "AD"
    assert initials("a") == "A"
    assert initials("Ada Lovelace") == "AL"
    assert initials("  ada   byron   lovelace  ") == "AL"


def test_harness_badge_table() -> None:
    assert harness_badge(HarnessId.CLAUDE_SDK) is HarnessBadge.CL
    assert harness_badge("codex") is HarnessBadge.CX
    assert harness_badge(HarnessId.COPILOT_SDK) is HarnessBadge.CP
    assert harness_badge(HarnessId.OPENCODE) is HarnessBadge.OM
    assert HARNESS_BADGES[HarnessId.OPENCODE] is HarnessBadge.OM
    with pytest.raises(ValueError):
        harness_badge("unknown-harness")
