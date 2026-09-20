"""Shared start and stop behavior for every managed-agent surface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Final

from textual import work

from band_wezterm.agent.adapters import HarnessUnavailableError
from band_wezterm.agent.launch import (
    AgentLaunchContext,
    AgentLaunchResources,
    prepare_agent_launch,
    rollback_agent_launch,
    spawn_agent_panes,
)
from band_wezterm.agent.native_console import NativeConsoleUnavailableError
from band_wezterm.agent.opencode_server import OpenCodeEndpoint
from band_wezterm.agent.readiness import preflight_managed_agent
from band_wezterm.client import AgentRecord
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.tui.stores import AgentPanes
from band_wezterm.wezterm_cli import WezTermCliError, kill_panes

if TYPE_CHECKING:
    from band_wezterm.tui.screens import ControlScreen

NO_WINDOW_MESSAGE: Final = "No WezTerm window — start the host with `band-wezterm`."
NO_MANAGED_KEY_MESSAGE: Final = (
    "No managed API key for this agent — re-register it from Control "
    "(keys are one-time at registration)."
)
NO_MANAGED_PROFILE_MESSAGE: Final = (
    "No local profile — register or reconfigure after upgrade."
)
STARTING_AGENT_MESSAGE: Final = "Starting {name}…"
AGENT_STARTING_MESSAGE: Final = "Agent is already starting."
ALREADY_STOPPED_MESSAGE: Final = "{name} is already stopped."
PANE_CLEANUP_FAILED_MESSAGE: Final = (
    "Agent start failed and its panes could not be closed; use Stop to retry cleanup."
)
PREFLIGHT_HARNESS_STABILITY_ATTEMPTS: Final = 5
PROFILE_HARNESS_UNSTABLE_MESSAGE: Final = (
    "Harness kept changing during preflight — try Start again."
)


class ManagedAgentActions:
    """Launch and stop one locally managed agent from a Control screen."""

    @property
    def _control_screen(self) -> ControlScreen:
        return self  # type: ignore[return-value]

    def _set_agent_operation_status(self, status: str) -> None:
        raise NotImplementedError

    def _refresh_agent_operation_view(self) -> None:
        raise NotImplementedError

    def start_managed_agent(self, agent: AgentRecord) -> None:
        store = self._control_screen.control.agents_store
        if store.is_running(agent.id):
            self._set_agent_operation_status(f"{agent.name} is already running.")
            return
        if store.is_starting(agent.id):
            self._set_agent_operation_status(AGENT_STARTING_MESSAGE)
            return
        store.begin_start(agent.id)
        self._set_agent_operation_status(STARTING_AGENT_MESSAGE.format(name=agent.name))
        self._start_managed_agent(agent)

    def stop_managed_agent(self, agent_id: str, agent_name: str) -> None:
        panes = self._control_screen.control.agents_store.running.get(agent_id)
        if panes is None:
            self._set_agent_operation_status(
                ALREADY_STOPPED_MESSAGE.format(name=agent_name)
            )
            return
        self._stop_managed_agent(agent_id, agent_name, panes)

    def _sync_agent_to_profile(
        self, agent: AgentRecord, profile: ManagedAgentProfile
    ) -> AgentRecord:
        if agent.harness is profile.harness:
            return agent
        updated = agent.model_copy(update={"harness": profile.harness})
        self._control_screen.control.agents_store.update_agent(updated)
        return updated

    def _resync_store_to_durable_profile(self, agent: AgentRecord) -> None:
        current = self._control_screen.control.managed_agents.get(agent.id)
        if current is None:
            return
        self._sync_agent_to_profile(agent, current)
        self._refresh_agent_operation_view()

    async def _preflight_launch_profile(
        self, agent_id: str, profile: ManagedAgentProfile
    ) -> ManagedAgentProfile | None:
        current = profile
        for _ in range(PREFLIGHT_HARNESS_STABILITY_ATTEMPTS):
            preflighted = current.harness
            try:
                await asyncio.to_thread(preflight_managed_agent, preflighted)
            except (HarnessUnavailableError, NativeConsoleUnavailableError) as error:
                self._set_agent_operation_status(str(error))
                return None
            fresh = self._control_screen.control.managed_agents.get(agent_id)
            if fresh is None:
                self._set_agent_operation_status(NO_MANAGED_PROFILE_MESSAGE)
                return None
            if fresh.harness is preflighted:
                return fresh
            current = fresh
        self._set_agent_operation_status(PROFILE_HARNESS_UNSTABLE_MESSAGE)
        return None

    async def _resolve_launch_context(
        self, agent: AgentRecord
    ) -> AgentLaunchContext | None:
        control = self._control_screen.control
        window_id = control.window_id
        api_key = control.client.managed_agent_api_key(agent.id)
        profile = control.managed_agents.get(agent.id)
        match window_id, api_key, profile:
            case None, _, _:
                self._set_agent_operation_status(NO_WINDOW_MESSAGE)
                return None
            case _, None | "", _:
                self._set_agent_operation_status(NO_MANAGED_KEY_MESSAGE)
                return None
            case _, _, None:
                self._set_agent_operation_status(NO_MANAGED_PROFILE_MESSAGE)
                return None
            case window_id, api_key, profile:
                agent = self._sync_agent_to_profile(agent, profile)

        preflighted = await self._preflight_launch_profile(agent.id, profile)
        if preflighted is None:
            self._resync_store_to_durable_profile(agent)
            return None
        fresh = control.managed_agents.get(agent.id)
        match fresh:
            case None:
                self._set_agent_operation_status(NO_MANAGED_PROFILE_MESSAGE)
                return None
            case fresh if fresh.harness is not preflighted.harness:
                self._sync_agent_to_profile(agent, fresh)
                self._set_agent_operation_status(PROFILE_HARNESS_UNSTABLE_MESSAGE)
                return None
            case fresh:
                return AgentLaunchContext(
                    agent=self._sync_agent_to_profile(agent, fresh),
                    api_key=api_key,
                    profile=fresh,
                    window_id=window_id,
                    cwd=Path.cwd(),
                )

    @work(group="managed-agent-start")
    async def _start_managed_agent(self, agent: AgentRecord) -> None:
        resources: AgentLaunchResources | None = None
        committed = False
        control = self._control_screen.control
        try:
            context = await self._resolve_launch_context(agent)
            if context is None or control.agents_store.is_running(agent.id):
                return
            endpoint = await self._opencode_endpoint(context)
            resources = prepare_agent_launch(context, opencode_endpoint=endpoint)
            panes = await spawn_agent_panes(context, resources)
            control.agents_store.mark_running(
                agent.id, panes.bridge, console=panes.console
            )
            committed = True
            self._set_agent_operation_status(
                f"Started {agent.name} ({context.profile.harness.value}) "
                "with private console and Band bridge."
            )
        except Exception as error:
            self._set_agent_operation_status(
                format_platform_error(error, operation="start agent")
            )
        finally:
            control.agents_store.finish_start(agent.id)
            if resources is not None and not committed:
                panes = await rollback_agent_launch(resources)
                if panes is not None:
                    control.agents_store.mark_running(
                        agent.id, panes.bridge, console=panes.console
                    )
                    self._set_agent_operation_status(PANE_CLEANUP_FAILED_MESSAGE)
            self._refresh_agent_operation_view()

    async def _opencode_endpoint(
        self, context: AgentLaunchContext
    ) -> OpenCodeEndpoint | None:
        match context.profile.harness:
            case HarnessId.OMP | HarnessId.OPENCODE:
                return await self._control_screen.control.opencode_server.ensure()
            case _:
                return None

    @work(exclusive=True, group="managed-agent-stop")
    async def _stop_managed_agent(
        self, agent_id: str, agent_name: str, panes: AgentPanes
    ) -> None:
        try:
            await asyncio.to_thread(kill_panes, panes.ids)
        except (WezTermCliError, OSError) as error:
            self._set_agent_operation_status(
                format_platform_error(error, operation="stop agent")
            )
            return
        self._control_screen.control.agents_store.mark_stopped(agent_id)
        self._set_agent_operation_status(f"Stopped {agent_name}.")
        self._refresh_agent_operation_view()
