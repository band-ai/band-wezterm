"""Shared managed-agent pane teardown."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from band_wezterm.tui.agent_teardown import kill_pane_ids, stop_tracked_agent
from band_wezterm.tui.stores import AgentPanes, AgentsStore
from band_wezterm.wezterm_cli import PaneId, WezTermCliError


@pytest.mark.asyncio
async def test_stop_tracked_agent_kills_and_marks_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AgentsStore()
    panes = AgentPanes(bridge=PaneId(1), console=PaneId(2))
    store.mark_running("a1", panes.bridge, console=panes.console)
    killed: list[tuple[PaneId, ...]] = []

    def fake_kill(ids: tuple[PaneId, ...]) -> None:
        killed.append(ids)

    monkeypatch.setattr(
        "band_wezterm.tui.agent_teardown.kill_panes", fake_kill
    )

    assert await stop_tracked_agent(store, "a1") is True
    assert killed == [panes.ids]
    assert "a1" not in store.running


@pytest.mark.asyncio
async def test_stop_tracked_agent_noop_when_not_running() -> None:
    store = AgentsStore()
    assert await stop_tracked_agent(store, "missing") is False


@pytest.mark.asyncio
async def test_stop_tracked_agent_leaves_running_when_kill_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AgentsStore()
    panes = AgentPanes(bridge=PaneId(3), console=PaneId(3))
    store.mark_running("a1", panes.bridge, console=panes.console)

    def boom(_ids: tuple[PaneId, ...]) -> None:
        raise WezTermCliError("nope")

    monkeypatch.setattr("band_wezterm.tui.agent_teardown.kill_panes", boom)

    with pytest.raises(WezTermCliError):
        await stop_tracked_agent(store, "a1", panes)
    assert "a1" in store.running


@pytest.mark.asyncio
async def test_kill_pane_ids_skips_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called = MagicMock()
    monkeypatch.setattr("band_wezterm.tui.agent_teardown.kill_panes", called)
    await kill_pane_ids(())
    called.assert_not_called()
