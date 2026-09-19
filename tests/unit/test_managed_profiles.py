"""Managed agent profile persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentStore, profile_from_registration

SAVE_FAILURE_MESSAGE = "disk full"


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
    profile = profile_from_registration(
        agent_id="a1",
        name="Alpha",
        harness=HarnessId.CODEX,
        persona=None,
        tuning=AgentTuning(),
    )
    replaced: list[tuple[str, str]] = []
    real_replace = __import__("os").replace

    def tracking_replace(src: str, dst: str) -> None:
        replaced.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr("band_wezterm.managed_profiles.os.replace", tracking_replace)
    store.record(profile)
    assert len(replaced) == 1
    src, dst = replaced[0]
    assert Path(dst) == path
    assert Path(src).parent == path.parent
    assert store.get("a1") == profile
    assert ManagedAgentStore(path).get("a1") == profile

