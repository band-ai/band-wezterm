"""Managed agent profile persistence."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentStore, profile_from_registration


def test_record_get_and_persona_update(tmp_path: Path) -> None:
    store = ManagedAgentStore(tmp_path / "profiles.json")
    profile = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CLAUDE_SDK,
        persona="# Developer\n",
        tuning=AgentTuning(model="opus"),
    )
    store.record(profile)
    loaded = ManagedAgentStore(tmp_path / "profiles.json")
    assert loaded.get("a1") == profile
    loaded.set_persona_and_tuning(
        "a1", persona="# Architect\n", tuning=AgentTuning(model="sonnet")
    )
    updated = loaded.get("a1")
    assert updated is not None
    assert updated.persona == "# Architect\n"
    assert updated.tuning.model == "sonnet"
