"""Stop and tear down managed-agent WezTerm panes — one path for every surface."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from band_wezterm.tui.stores import AgentPanes, AgentsStore
from band_wezterm.wezterm_cli import PaneId, kill_panes


async def kill_pane_ids(pane_ids: Sequence[PaneId]) -> None:
    """Close the given panes (no-op when empty)."""
    if not pane_ids:
        return
    await asyncio.to_thread(kill_panes, pane_ids)


async def stop_tracked_agent(
    agents_store: AgentsStore,
    agent_id: str,
    panes: AgentPanes | None = None,
) -> bool:
    """Kill an agent's tracked panes and mark it stopped.

    Returns False when the agent was not running. Raises WezTerm/OS errors from
    ``kill_panes`` without marking stopped so callers can retry.
    """
    target = panes if panes is not None else agents_store.running.get(agent_id)
    if target is None:
        return False
    await kill_pane_ids(target.ids)
    agents_store.mark_stopped(agent_id)
    return True
