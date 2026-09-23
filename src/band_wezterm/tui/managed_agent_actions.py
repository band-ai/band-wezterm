"""Shared start and stop behavior for every managed-agent surface."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Final

from textual import work

from band_wezterm.agent.adapters import HarnessUnavailableError
from band_wezterm.agent.readiness import preflight_managed_agent
from band_wezterm.client import AgentRecord
from band_wezterm.errors import format_platform_error
from band_wezterm.managed_profiles import ManagedAgentProfile

if TYPE_CHECKING:
    from band_wezterm.tui.screens import ControlScreen

NO_MANAGED_PROFILE_MESSAGE: Final = (
    "No local profile — register or reconfigure after upgrade."
)
NO_MANAGED_KEY_MESSAGE: Final = (
    "No managed API key for this agent — re-register it from `band agent` "
    "(keys are one-time at registration)."
)
STARTING_AGENT_MESSAGE: Final = "Starting {name}…"
AGENT_STARTING_MESSAGE: Final = "Agent is already starting."
ALREADY_STOPPED_MESSAGE: Final = "{name} is already stopped."
PREFLIGHT_HARNESS_STABILITY_ATTEMPTS: Final = 5
PROFILE_HARNESS_UNSTABLE_MESSAGE: Final = (
    "Harness kept changing during preflight — try Start again."
)
PANE_CLEANUP_FAILED_MESSAGE: Final = (
    "Agent start failed and its panes could not be closed; use Stop to retry cleanup."
)


class ManagedAgentActions:
    """Launch and stop one locally managed agent from a Band screen."""

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
        if not self._control_screen.control.agents_store.is_running(agent_id):
            self._set_agent_operation_status(
                ALREADY_STOPPED_MESSAGE.format(name=agent_name)
            )
            return
        self._stop_managed_agent(agent_id, agent_name)

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
        self,
        agent_id: str,
        profile: ManagedAgentProfile,
    ) -> ManagedAgentProfile | None:
        current = profile
        for _ in range(PREFLIGHT_HARNESS_STABILITY_ATTEMPTS):
            preflighted = current.harness
            try:
                await asyncio.to_thread(
                    preflight_managed_agent,
                    preflighted,
                    cwd=Path.cwd(),
                    persona=current.persona,
                    tuning=current.tuning,
                )
            except HarnessUnavailableError as error:
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

    async def _ready_managed_profile(
        self,
        agent: AgentRecord,
    ) -> tuple[AgentRecord, ManagedAgentProfile] | None:
        """Load, preflight, and sync one durable profile for start or attach."""
        control = self._control_screen.control
        profile = control.managed_agents.get(agent.id)
        if profile is None:
            self._set_agent_operation_status(NO_MANAGED_PROFILE_MESSAGE)
            return None
        agent = self._sync_agent_to_profile(agent, profile)
        preflighted = await self._preflight_launch_profile(
            agent.id,
            profile,
        )
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
                return self._sync_agent_to_profile(agent, fresh), fresh

    @work(group="managed-agent-start")
    async def _start_managed_agent(self, agent: AgentRecord) -> None:
        control = self._control_screen.control
        try:
            ready = await self._ready_managed_profile(agent)
            if ready is None or control.agents_store.is_running(agent.id):
                return
            resolved, profile = ready
            worker = await control.supervisor.start(resolved.id, cwd=Path.cwd())
            control.agents_store.mark_worker(worker)
            self._set_agent_operation_status(
                f"Started {resolved.name} ({profile.harness.value}) as a detached worker."
            )
        except Exception as error:
            self._set_agent_operation_status(
                format_platform_error(error, operation="start agent")
            )
        finally:
            control.agents_store.finish_start(agent.id)
            self._refresh_agent_operation_view()

    @work(exclusive=True, group="managed-agent-stop")
    async def _stop_managed_agent(self, agent_id: str, agent_name: str) -> None:
        try:
            control = self._control_screen.control
            worker = await control.supervisor.stop(agent_id)
            if worker is None:
                control.agents_store.mark_stopped(agent_id)
            else:
                control.agents_store.mark_worker(worker)
        except Exception as error:
            self._set_agent_operation_status(
                format_platform_error(error, operation="stop agent")
            )
            return
        self._set_agent_operation_status(f"Stopping {agent_name}.")
        self._refresh_agent_operation_view()
