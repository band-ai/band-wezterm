"""Long-running agent pane — Agent.create + run_forever."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

from band import Agent
from band.runtime.types import AgentConfig

from band_wezterm.agent.adapters import build_adapter
from band_wezterm.agent.spawn_cmd import tuning_from_cli
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
from band_wezterm.pane_identity import announce_agent_pane, announce_runtime_status

AGENT_TAB_TITLE = "Band agent"
AGENT_TAB_ONLINE = "Online — listening to Band rooms"
AGENT_TAB_HINT = "Read and send messages in Control. Press Ctrl+C to stop this agent."
DEFAULT_TUNING_VALUE = "automatic"


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
            "Managed agent API key missing — re-register the agent from Control."
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
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    agent_id = args.agent_id.strip()
    name = (args.name or agent_id).strip() or agent_id
    harness = args.harness.strip() or None
    if not agent_id:
        print("BAND_AGENT_ID / --agent-id is required", file=sys.stderr)
        return 2

    announce_agent_pane(agent_id, name, harness)
    failed = False
    try:
        api_key = _read_api_key(args.key_file)
        persona = _read_persona(args.persona_file)
        tuning = tuning_from_cli(
            model=args.model.strip() or None,
            reasoning=args.reasoning.strip() or None,
        )
        settings = load_settings()
        adapter = build_adapter(
            harness,
            cwd=args.cwd,
            persona=persona,
            tuning=tuning,
            opencode_server_url=args.opencode_server_url,
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
            # Re-announce full identity once the PTY is live — early STARTING OSC
            # can race spawn/focus restore and leave the tab uncolored.
            announce_agent_pane(
                agent_id, name, harness, runtime=AgentRuntime.RUNNING
            )
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
            await agent.run_forever()
    except Exception as error:
        failed = True
        message = format_platform_error(error, operation="agent runtime")
        announce_runtime_status(AgentRuntime.ERROR)
        print(f"Agent runtime failed: {message}", file=sys.stderr)
        return 1
    finally:
        if not failed:
            log_event("agent stopping", agent_id=agent_id)
            announce_runtime_status(AgentRuntime.STOPPING)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_diagnostics()
    return asyncio.run(run(parse_args(argv)))
