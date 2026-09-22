"""Transactional WezTerm launch for one managed agent."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from band_wezterm.agent.native_console import (
    build_native_console,
    native_console_command,
    write_native_console_launch,
)
from band_wezterm.agent.opencode_server import OpenCodeEndpoint
from band_wezterm.agent.spawn_cmd import (
    agent_pane_command,
    write_api_key_file,
    write_persona_file,
)
from band_wezterm.client import AgentRecord
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.tui.stores import AgentPanes
from band_wezterm.wezterm_cli import (
    PaneId,
    WezTermCliError,
    WindowId,
    activate_pane,
    kill_panes,
    set_tab_title,
    spawn_additional_tab,
    split_pane,
)


@dataclass(frozen=True)
class AgentLaunchContext:
    """Validated inputs for one Band-bridge launch (optionally with native console)."""

    agent: AgentRecord
    api_key: str
    profile: ManagedAgentProfile
    window_id: WindowId
    cwd: Path
    interactive_console: bool = False
    focus_pane: PaneId | None = None


@dataclass
class AgentLaunchResources:
    """Temporary files and panes owned until a launch commits."""

    key_file: Path | None = None
    persona_file: Path | None = None
    console_launch_file: Path | None = None
    console_command: list[str] = field(default_factory=list)
    bridge_command: list[str] = field(default_factory=list)
    acquired_panes: list[PaneId] = field(default_factory=list)

    def remove_private_files(self) -> None:
        for path in (self.key_file, self.persona_file, self.console_launch_file):
            if path is not None:
                path.unlink(missing_ok=True)


def prepare_agent_launch(
    context: AgentLaunchContext,
    *,
    opencode_endpoint: OpenCodeEndpoint | None = None,
) -> AgentLaunchResources:
    """Create private handoff files and commands before opening any pane."""
    resources = AgentLaunchResources()
    try:
        resources.key_file = write_api_key_file(context.api_key)
        instructions = context.profile.runtime_instructions()
        if instructions:
            resources.persona_file = write_persona_file(instructions)
        if context.interactive_console:
            console = build_native_console(context.profile, cwd=context.cwd)
            resources.console_launch_file = write_native_console_launch(console)
            resources.console_command = native_console_command(
                agent_id=context.agent.id,
                name=context.agent.name,
                harness=context.profile.harness,
                launch_file=resources.console_launch_file,
            )
        resources.bridge_command = agent_pane_command(
            context.agent,
            key_file=resources.key_file,
            cwd=context.cwd,
            profile=context.profile,
            persona_file=resources.persona_file,
            opencode_endpoint=opencode_endpoint,
        )
    except Exception:
        resources.remove_private_files()
        raise
    return resources


async def spawn_agent_panes(
    context: AgentLaunchContext, resources: AgentLaunchResources
) -> AgentPanes:
    """Open and title the agent tab, then restore focus to Control.

    ``wezterm cli spawn`` always activates the new tab; re-activating
    ``focus_pane`` keeps the user on Control.
    """
    if context.interactive_console:
        console = await _spawn_pane(
            lambda: spawn_additional_tab(
                context.window_id, context.cwd, resources.console_command
            ),
            resources.acquired_panes,
        )
        await asyncio.to_thread(set_tab_title, console, context.agent.name)
        bridge = await _spawn_pane(
            lambda: split_pane(console, context.cwd, resources.bridge_command),
            resources.acquired_panes,
        )
        panes = AgentPanes(bridge=bridge, console=console)
    else:
        bridge = await _spawn_pane(
            lambda: spawn_additional_tab(
                context.window_id, context.cwd, resources.bridge_command
            ),
            resources.acquired_panes,
        )
        await asyncio.to_thread(set_tab_title, bridge, context.agent.name)
        panes = AgentPanes(bridge=bridge, console=bridge)
    await _restore_control_focus(context.focus_pane)
    return panes


async def _restore_control_focus(focus_pane: PaneId | None) -> None:
    if focus_pane is None:
        return
    await asyncio.to_thread(activate_pane, focus_pane)


async def rollback_agent_launch(resources: AgentLaunchResources) -> AgentPanes | None:
    """Release uncommitted resources, returning panes that could not be closed."""
    resources.remove_private_files()
    if not resources.acquired_panes:
        return None
    try:
        await asyncio.shield(asyncio.to_thread(kill_panes, resources.acquired_panes))
    except (WezTermCliError, OSError):
        first = resources.acquired_panes[0]
        last = resources.acquired_panes[-1]
        return AgentPanes(bridge=last, console=first)
    return None


async def _spawn_pane(create: Callable[[], PaneId], acquired: list[PaneId]) -> PaneId:
    """Keep ownership of a thread-created pane even if the worker is cancelled."""
    task = asyncio.create_task(asyncio.to_thread(create))
    try:
        pane_id = await asyncio.shield(task)
    except asyncio.CancelledError:
        pane_id = await task
        acquired.append(pane_id)
        raise
    acquired.append(pane_id)
    return pane_id
