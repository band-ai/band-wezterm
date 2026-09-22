"""Long-running agent pane — Agent.create + run_forever."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import secrets
import sys
from pathlib import Path
from typing import Final

from band import Agent
from band.runtime.types import AgentConfig

from band_wezterm.agent.adapters import build_adapter
from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.agent.spawn_cmd import tuning_from_cli
from band_wezterm.auth.credentials import ManagedAgentKeyStore
from band_wezterm.backends import AgentTuning, TuningDimensionId
from band_wezterm.config import (
    AGENT_API_KEY_ENV,
    AGENT_HARNESS_ENV,
    AGENT_ID_ENV,
    AGENT_MODEL_ENV,
    AGENT_NAME_ENV,
    AGENT_PERSONA_FILE_ENV,
    AGENT_REASONING_ENV,
    load_settings,
)
from band_wezterm.diagnostics import configure_diagnostics, log_event
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import AgentRuntime
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.pane_identity import announce_agent_pane, announce_runtime_status
from band_wezterm.supervisor.protocol import (
    WorkerAction,
    WorkerRequest,
    WorkerResponse,
    WorkerState,
)

AGENT_TAB_TITLE = "Band agent"
AGENT_TAB_ONLINE = "Online — listening to Band rooms"
AGENT_TAB_HINT = "Read and send messages in a Band room view. Press Ctrl+C to stop this agent."
DEFAULT_TUNING_VALUE = "automatic"
WORKER_SOCKET_MODE: Final = 0o600


class WorkerController:
    """Authenticated stop/status endpoint owned by one detached worker."""

    def __init__(self, socket_path: Path | None, token: str) -> None:
        self._socket_path = socket_path
        self._token = token
        self._state = WorkerState.STARTING
        self.stop_requested = asyncio.Event()
        self._server: asyncio.Server | None = None

    @property
    def enabled(self) -> bool:
        return self._socket_path is not None and bool(self._token)

    async def start(self) -> None:
        if not self.enabled:
            return
        assert self._socket_path is not None
        self._socket_path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=str(self._socket_path)
        )
        self._socket_path.chmod(WORKER_SOCKET_MODE)

    def mark_running(self) -> None:
        self._state = WorkerState.RUNNING

    def mark_error(self) -> None:
        self._state = WorkerState.ERROR

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        if self._socket_path is not None:
            self._socket_path.unlink(missing_ok=True)

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = WorkerRequest.model_validate_json(await reader.readline())
            if not secrets.compare_digest(request.token, self._token):
                raise PermissionError("authentication failed")
            match request.action:
                case WorkerAction.STATUS:
                    response = WorkerResponse(ok=True, state=self._state)
                case WorkerAction.STOP:
                    self._state = WorkerState.STOPPING
                    self.stop_requested.set()
                    response = WorkerResponse(ok=True, state=self._state)
                case _:
                    response = WorkerResponse(
                        ok=False, state=self._state, error="unsupported worker request"
                    )
        except (PermissionError, ValueError) as error:
            response = WorkerResponse(ok=False, state=self._state, error=str(error))
        writer.write(response.model_dump_json().encode() + b"\n")
        with contextlib.suppress(OSError):
            await writer.drain()
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


def _read_api_key(key_file: Path | None) -> str:
    if key_file is not None:
        try:
            key = key_file.read_text(encoding="utf-8").strip()
        finally:
            with contextlib.suppress(OSError):
                key_file.unlink(missing_ok=True)
        if key:
            return key
    env_key = os.environ.get(AGENT_API_KEY_ENV, "").strip()
    if not env_key:
        raise RuntimeError(
            "Managed agent API key missing — re-register the agent from Band home."
        )
    return env_key


def _read_persona(persona_file: Path | None) -> str | None:
    if persona_file is None:
        env_path = os.environ.get(AGENT_PERSONA_FILE_ENV, "").strip()
        persona_file = Path(env_path) if env_path else None
    if persona_file is None:
        return None
    try:
        text = persona_file.read_text(encoding="utf-8")
    finally:
        with contextlib.suppress(OSError):
            persona_file.unlink(missing_ok=True)
    return text or None


def runtime_banner(
    *, name: str, harness: str | None, tuning: AgentTuning, cwd: Path
) -> str:
    """Describe the live agent in its terminal pane."""
    model = tuning.value_for(TuningDimensionId.MODEL) or DEFAULT_TUNING_VALUE
    reasoning = tuning.value_for(TuningDimensionId.REASONING) or DEFAULT_TUNING_VALUE
    runtime = harness or "unknown"
    return "\n".join(
        (
            AGENT_TAB_TITLE,
            f"  Agent: {name}",
            f"  Runtime: {runtime}",
            f"  Model: {model}",
            f"  Reasoning: {reasoning}",
            f"  Working directory: {cwd}",
            "",
            f"  Status: {AGENT_TAB_ONLINE}",
            f"  {AGENT_TAB_HINT}",
            "",
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.agent")
    parser.add_argument("--agent-id", default=os.environ.get(AGENT_ID_ENV, ""))
    parser.add_argument("--harness", default=os.environ.get(AGENT_HARNESS_ENV, ""))
    parser.add_argument("--name", default=os.environ.get(AGENT_NAME_ENV, ""))
    parser.add_argument("--key-file", type=Path, default=None)
    parser.add_argument("--persona-file", type=Path, default=None)
    parser.add_argument("--model", default=os.environ.get(AGENT_MODEL_ENV, ""))
    parser.add_argument("--reasoning", default=os.environ.get(AGENT_REASONING_ENV, ""))
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--opencode-server-url", default=None)
    parser.add_argument("--managed", action="store_true")
    parser.add_argument("--control-socket", type=Path, default=None)
    parser.add_argument("--control-token", default="")
    return parser.parse_args(argv)


def _managed_launch_values(
    args: argparse.Namespace,
) -> tuple[str, str, str, str | None, AgentTuning]:
    profile = ManagedAgentStore().get(args.agent_id)
    if profile is None:
        raise RuntimeError("Managed agent profile missing.")
    api_key = ManagedAgentKeyStore().get(args.agent_id)
    if api_key is None:
        raise RuntimeError("Managed agent API key missing.")
    return (
        profile.name,
        profile.harness.value,
        api_key,
        profile.runtime_instructions(),
        profile.tuning,
    )


async def run(args: argparse.Namespace) -> int:
    agent_id = args.agent_id.strip()
    if not agent_id:
        print("BAND_AGENT_ID / --agent-id is required", file=sys.stderr)
        return 2

    controller = WorkerController(args.control_socket, args.control_token.strip())
    failed = False
    opencode_server: OpenCodeServerManager | None = None
    try:
        if args.managed:
            name, harness, api_key, persona, tuning = _managed_launch_values(args)
        else:
            name = (args.name or agent_id).strip() or agent_id
            harness = args.harness.strip() or None
            api_key = _read_api_key(args.key_file)
            persona = _read_persona(args.persona_file)
            tuning = tuning_from_cli(
                model=args.model.strip() or None,
                reasoning=args.reasoning.strip() or None,
            )
        announce_agent_pane(agent_id, name, harness)
        settings = load_settings()
        if harness in {"omp", "opencode"}:
            opencode_server = OpenCodeServerManager()
            opencode_endpoint = await opencode_server.ensure()
            opencode_server_url = opencode_endpoint.url
        else:
            opencode_server_url = args.opencode_server_url
        adapter = build_adapter(
            harness,
            cwd=args.cwd,
            persona=persona,
            tuning=tuning,
            opencode_server_url=opencode_server_url,
        )
        config = AgentConfig(auto_subscribe_existing_rooms=True, single_instance=True)
        agent = Agent.create(
            adapter=adapter,
            agent_id=agent_id,
            api_key=api_key,
            rest_url=settings.band_base_url,
            ws_url=settings.band_ws_url,
            config=config,
        )
        async with agent:
            await controller.start()
            controller.mark_running()
            # Re-announce full identity once the PTY is live — early STARTING OSC
            # can race spawn/focus restore and leave the tab uncolored.
            announce_agent_pane(agent_id, name, harness, runtime=AgentRuntime.RUNNING)
            log_event("agent started", agent_id=agent_id, harness=harness or "unknown")
            print(
                runtime_banner(
                    name=name,
                    harness=harness,
                    tuning=tuning,
                    cwd=args.cwd,
                ),
                flush=True,
            )
            agent_task = asyncio.create_task(agent.run_forever())
            stop_task = asyncio.create_task(controller.stop_requested.wait())
            done, _pending = await asyncio.wait(
                {agent_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done:
                await agent.stop()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(agent_task, timeout=5)
                if not agent_task.done():
                    agent_task.cancel()
                    await asyncio.gather(agent_task, return_exceptions=True)
            else:
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
                await agent_task
    except Exception as error:
        failed = True
        controller.mark_error()
        message = format_platform_error(error, operation="agent runtime")
        announce_runtime_status(AgentRuntime.ERROR)
        print(f"Agent runtime failed: {message}", file=sys.stderr)
        return 1
    finally:
        await controller.close()
        if opencode_server is not None:
            await opencode_server.close()
        if not failed:
            log_event("agent stopping", agent_id=agent_id)
            announce_runtime_status(AgentRuntime.STOPPING)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_diagnostics()
    return asyncio.run(run(parse_args(argv)))
