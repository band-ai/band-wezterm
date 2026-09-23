"""AgentsStore add/update/remove."""

from __future__ import annotations

from band_wezterm.client import AgentRecord
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent
from band_wezterm.supervisor import WorkerRecord, WorkerState
from band_wezterm.tui.stores import AgentsStore


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
    store.mark_worker(_worker("a1", "Alpha"))
    store.update_agent(alpha.model_copy(update={"harness": HarnessId.CODEX}))
    assert store.find("a1") is not None
    assert store.find("a1").harness is HarnessId.CODEX
    store.remove_agent("a1")
    assert store.find("a1") is None
    assert store.is_running("a1") is False


def test_running_agent_uses_supervisor_state() -> None:
    store = AgentsStore()
    store.mark_worker(_worker("a1", "Alpha"))
    assert store.is_running("a1") is True


def _worker(agent_id: str, name: str) -> WorkerRecord:
    return WorkerRecord(
        agent_id=agent_id,
        name=name,
        pid=9,
        control_socket="/tmp/worker.sock",
        control_token="token",
        cwd="/tmp",
        started_at=0,
        state=WorkerState.RUNNING,
    )


def test_catalog_changes_keep_selection_on_a_visible_agent() -> None:
    alpha = _agent("a1", "Alpha")
    beta = _agent("b1", "Beta")
    store = AgentsStore(agents=[alpha, beta], selected_id=beta.id)

    store.set_search("Alpha")

    assert store.selected_id == alpha.id

    store.replace_agents([beta])

    assert store.selected_id is None

    store.set_search("")

    assert store.selected_id == beta.id


def test_remove_clears_in_flight_delete_state() -> None:
    alpha = _agent("a1", "Alpha")
    store = AgentsStore(agents=[alpha])
    store.begin_delete(alpha.id)

    store.remove_agent(alpha.id)

    assert store.is_deleting(alpha.id) is False
