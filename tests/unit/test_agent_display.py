"""Durable configuration is faithfully summarized for every catalog surface."""

from band_wezterm.agent_display import AgentConfigurationLabel, agent_configuration
from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile


def test_agent_configuration_does_not_invent_unmanaged_details() -> None:
    assert agent_configuration(None).role == AgentConfigurationLabel.UNMANAGED


def test_agent_configuration_projects_role_and_tuning() -> None:
    profile = ManagedAgentProfile(
        agent_id="agent-1",
        name="Architect",
        harness=HarnessId.CODEX,
        persona="# System Architect\n",
        tuning=AgentTuning(model="gpt-5.6-sol", reasoning="high"),
    )

    display = agent_configuration(profile)

    assert display.role == "Custom"
    assert display.model == "gpt-5.6-sol"
    assert display.options == "Reasoning effort: high"
