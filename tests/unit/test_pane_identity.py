"""Managed-agent pane OSC identity fields."""

from __future__ import annotations

import pytest

from band_wezterm.agent.pane_identity import agent_identity_fields, announce_agent_pane
from band_wezterm.identity import AgentRuntime, AvatarKind, agent_accent
from band_wezterm.osc import OscKey

AGENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
AGENT_NAME = "Developer"


def test_agent_identity_fields_include_accent_color_and_runtime() -> None:
    fields = agent_identity_fields(
        AGENT_ID,
        AGENT_NAME,
        "copilot_sdk",
        runtime=AgentRuntime.RUNNING,
    )

    assert fields[OscKey.AGENT_ID] == AGENT_ID
    assert fields[OscKey.AGENT_NAME] == AGENT_NAME
    assert fields[OscKey.AGENT_COLOR] == agent_accent(AGENT_ID)
    assert fields[OscKey.AGENT_KIND] == AvatarKind.AGENT.value
    assert fields[OscKey.AGENT_RUNTIME] == AgentRuntime.RUNNING.value
    assert OscKey.AGENT_HARNESS in fields


def test_announce_agent_pane_writes_identity_osc(
    capsys: pytest.CaptureFixture[str],
) -> None:
    announce_agent_pane(AGENT_ID, AGENT_NAME, None, runtime=AgentRuntime.STARTING)

    captured = capsys.readouterr().out
    assert "band.agent.color=" in captured
    assert "band.agent.name=" in captured
    assert "band.agent.runtime=" in captured
