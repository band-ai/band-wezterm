"""AgentsStore filter chips are exclusive; All means no predicate."""

from __future__ import annotations

from band_wezterm.client import AgentRecord
from band_wezterm.identity import AvatarKind, HarnessId
from band_wezterm.supervisor import WorkerRecord, WorkerState
from band_wezterm.tui.stores import AgentFilter, AgentsStore


def _agent(agent_id: str, name: str, *, harness: HarnessId | None = None) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        name=name,
        kind=AvatarKind.AGENT,
        color="#355dd4",
        harness=harness,
    )


def test_all_shows_entire_catalog() -> None:
    store = AgentsStore(
        agents=[_agent("1", "Alpha"), _agent("2", "Beta")],
        filter=AgentFilter.ALL,
    )
    assert [agent.name for agent in store.visible] == ["Alpha", "Beta"]


def test_select_filter_replaces_previous() -> None:
    store = AgentsStore(
        agents=[
            _agent("1", "Alpha"),
            _agent("2", "Beta", harness=HarnessId.CLAUDE),
        ],
    )
    store.mark_worker(
        WorkerRecord(
            agent_id="1",
            name="Alpha",
            pid=7,
            control_socket="/tmp/worker.sock",
            control_token="token",
            cwd="/tmp",
            started_at=0,
            state=WorkerState.RUNNING,
        )
    )
    store.select_filter(AgentFilter.RUNNING)
    assert [agent.name for agent in store.visible] == ["Alpha"]
    store.select_filter(AgentFilter.CLAUDE)
    assert [agent.name for agent in store.visible] == ["Beta"]
    store.select_filter(AgentFilter.ALL)
    assert [agent.name for agent in store.visible] == ["Alpha", "Beta"]
