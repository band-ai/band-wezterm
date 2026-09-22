"""Managed agent profile persistence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentStore, profile_from_registration

SAVE_FAILURE_MESSAGE = "disk full"


def test_runtime_instructions_bind_identity_to_the_role_snapshot() -> None:
    profile = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona="# Product Manager\nPrioritize user outcomes.\n",
        tuning=AgentTuning(),
    )

    assert profile.runtime_instructions() == (
        "You are Alpha, a Band-managed agent.\n"
        "Apply the role specification below to every response and action. When asked "
        "who you are, introduce yourself using your Band agent name and the role "
        "described below; do not describe yourself only as the underlying harness.\n"
        "\n# Product Manager\nPrioritize user outcomes.\n"
    )


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


def test_load_migrates_the_rejected_codex_model_alias(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(
        """{
  "profiles": [
    {
      "agent_id": "a1",
      "name": "Alpha",
      "harness": "codex",
      "tuning": {"model": "gpt-5.6", "reasoning": "low"}
    }
  ]
}
""",
        encoding="utf-8",
    )

    profile = ManagedAgentStore(path).get("a1")

    assert profile is not None
    assert profile.tuning.model == "gpt-5.6-sol"
    assert '"model": "gpt-5.6-sol"' in path.read_text(encoding="utf-8")


def test_record_rolls_back_memory_when_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ManagedAgentStore(tmp_path / "profiles.json")
    existing = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona=None,
        tuning=AgentTuning(),
    )
    store.record(existing)

    def boom() -> None:
        raise OSError(SAVE_FAILURE_MESSAGE)

    monkeypatch.setattr(store, "_save", boom)

    replacement = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CLAUDE,
        persona=None,
        tuning=AgentTuning(),
    )
    with pytest.raises(OSError, match=SAVE_FAILURE_MESSAGE):
        store.record(replacement)
    assert store.get("a1") == existing

    fresh = profile_from_registration(
        agent_id="a2",
        name="Beta",
        harness=HarnessId.COPILOT,
        persona=None,
        tuning=AgentTuning(),
    )
    with pytest.raises(OSError, match=SAVE_FAILURE_MESSAGE):
        store.record(fresh)
    assert store.get("a2") is None


def test_remove_rolls_back_memory_when_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ManagedAgentStore(tmp_path / "profiles.json")
    existing = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona=None,
        tuning=AgentTuning(),
    )
    store.record(existing)

    def boom() -> None:
        raise OSError(SAVE_FAILURE_MESSAGE)

    monkeypatch.setattr(store, "_save", boom)
    with pytest.raises(OSError, match=SAVE_FAILURE_MESSAGE):
        store.remove("a1")
    assert store.get("a1") == existing


def test_save_is_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "profiles.json"
    store = ManagedAgentStore(path)
    existing = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona=None,
        tuning=AgentTuning(),
    )
    store.record(existing)
    prior_content = path.read_text(encoding="utf-8")

    def fail_before_replace(_src: str, _dst: str) -> None:
        raise OSError(SAVE_FAILURE_MESSAGE)

    monkeypatch.setattr("band_wezterm.managed_profiles.os.replace", fail_before_replace)
    replacement = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CLAUDE,
        persona=None,
        tuning=AgentTuning(),
    )
    with pytest.raises(OSError, match=SAVE_FAILURE_MESSAGE):
        store.record(replacement)

    assert path.read_text(encoding="utf-8") == prior_content
    assert store.get("a1") == existing
    assert list(tmp_path.glob(".managed_agents.*.tmp")) == []


def test_set_persona_and_tuning_rolls_back_memory_when_save_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ManagedAgentStore(tmp_path / "profiles.json")
    existing = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona="# Dev\n",
        tuning=AgentTuning(model="opus"),
    )
    store.record(existing)

    def boom() -> None:
        raise OSError(SAVE_FAILURE_MESSAGE)

    monkeypatch.setattr(store, "_save", boom)
    with pytest.raises(OSError, match=SAVE_FAILURE_MESSAGE):
        store.set_persona_and_tuning(
            "a1", persona="# Architect\n", tuning=AgentTuning(model="sonnet")
        )
    assert store.get("a1") == existing


def test_save_unlinks_temp_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "profiles.json"
    store = ManagedAgentStore(path)
    profile = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona=None,
        tuning=AgentTuning(),
    )

    def boom_fdopen(fd: int, *_args: object, **_kwargs: object) -> object:
        os.close(fd)
        raise OSError(SAVE_FAILURE_MESSAGE)

    monkeypatch.setattr("band_wezterm.managed_profiles.os.fdopen", boom_fdopen)
    with pytest.raises(OSError, match=SAVE_FAILURE_MESSAGE):
        store.record(profile)
    assert list(tmp_path.glob(".managed_agents.*.tmp")) == []
    assert store.get("a1") is None

def test_ids_returns_frozen_agent_id_set(tmp_path: Path) -> None:
    store = ManagedAgentStore(tmp_path / "profiles.json")
    store.record(
        profile_from_registration(
            agent_id="a1",
            name="Alpha",
            harness=HarnessId.CLAUDE_SDK,
            persona=None,
            tuning=AgentTuning(),
        )
    )
    store.record(
        profile_from_registration(
            agent_id="a2",
            name="Beta",
            harness=HarnessId.CODEX,
            persona=None,
            tuning=AgentTuning(),
        )
    )

    assert store.ids() == frozenset({"a1", "a2"})

