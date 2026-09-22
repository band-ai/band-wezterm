"""WezTerm pane identity OSC helpers."""

from __future__ import annotations

import pytest

from band_wezterm.identity import AgentRuntime, AvatarKind, agent_accent
from band_wezterm.osc import OscKey
from band_wezterm.pane_identity import (
    CONTROL_HUMAN_NAME,
    agent_identity_fields,
    announce_agent_pane,
    announce_control_human,
    announce_human_pane,
    announce_runtime_status,
    pane_identity_fields,
)

AGENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
AGENT_NAME = "Developer"
HOST_NAME = "You"


def test_pane_identity_fields_shared_shape_for_human_and_agent() -> None:
    human = pane_identity_fields(AGENT_ID, HOST_NAME, kind=AvatarKind.HUMAN)
    agent = agent_identity_fields(
        AGENT_ID, AGENT_NAME, "copilot_sdk", runtime=AgentRuntime.RUNNING
    )

    assert human[OscKey.AGENT_KIND] == AvatarKind.HUMAN.value
    assert OscKey.AGENT_RUNTIME not in human
    assert agent[OscKey.AGENT_KIND] == AvatarKind.AGENT.value
    assert agent[OscKey.AGENT_COLOR] == agent_accent(AGENT_ID)
    assert agent[OscKey.AGENT_RUNTIME] == AgentRuntime.RUNNING.value
    assert OscKey.AGENT_HARNESS in agent


def test_announce_agent_pane_writes_identity_osc(
    capsys: pytest.CaptureFixture[str],
) -> None:
    announce_agent_pane(AGENT_ID, AGENT_NAME, None, runtime=AgentRuntime.STARTING)

    captured = capsys.readouterr().out
    assert "band.agent.color=" in captured
    assert "band.agent.name=" in captured
    assert "band.agent.runtime=" in captured


def test_announce_human_pane_writes_human_kind(
    capsys: pytest.CaptureFixture[str],
) -> None:
    announce_human_pane(AGENT_ID, HOST_NAME)

    captured = capsys.readouterr().out
    assert "band.agent.kind=" in captured
    assert "band.agent.color=" in captured


def test_announce_runtime_status_writes_offline_pair(
    capsys: pytest.CaptureFixture[str],
) -> None:
    announce_runtime_status(AgentRuntime.ERROR)

    captured = capsys.readouterr().out
    assert "band.agent.runtime=" in captured
    assert "band.agent.status=" in captured


def test_announce_control_human_uses_shared_display_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    announce_control_human(AGENT_ID)
    captured = capsys.readouterr().out
    assert "band.agent.color=" in captured
    assert CONTROL_HUMAN_NAME
