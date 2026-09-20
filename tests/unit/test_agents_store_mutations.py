"""AgentsStore add/update/remove."""

from __future__ import annotations

from band_wezterm.client import AgentRecord
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent
from band_wezterm.tui.stores import AgentPanes, AgentsStore
from band_wezterm.wezterm_cli import PaneId


def _agent(agent_id: str, name: str, harness: HarnessId = HarnessId.CLAUDE_SDK) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        name=name,
        kind=AvatarKind.AGENT,
        color=agent_accent(agent_id),
        harness=harness,
    )


def test_update_and_remove_agent() -> None:
    store = AgentsStore()
    alpha = _agent("a1", "Alpha")
    store.add_agent(alpha)
    store.mark_running("a1", PaneId(9))
    store.update_agent(alpha.model_copy(update={"harness": HarnessId.CODEX}))
    assert store.find("a1") is not None
    assert store.find("a1").harness is HarnessId.CODEX
    store.remove_agent("a1")
    assert store.find("a1") is None
    assert store.is_running("a1") is False


def test_running_agent_tracks_console_and_bridge_as_one_lifecycle() -> None:
    store = AgentsStore()
    console = PaneId(9)
    bridge = PaneId(10)

    store.mark_running("a1", bridge, console=console)

    assert store.running["a1"] == AgentPanes(console=console, bridge=bridge)
    assert store.prune_running([9, 10]) == []
    assert store.prune_running([9]) == ["a1"]
    assert store.is_running("a1") is False
