"""Long-running agent pane — Agent.create + run_forever."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from band import Agent
from band.runtime.types import AgentConfig

from band_wezterm.agent.adapters import build_adapter
from band_wezterm.config import (
    AGENT_API_KEY_ENV,
    AGENT_HARNESS_ENV,
    AGENT_ID_ENV,
    AGENT_NAME_ENV,
    load_settings,
)
from band_wezterm.identity import (
    AgentRuntime,
    AgentStatus,
    AvatarKind,
    agent_accent,
    harness_badge,
    initials,
    parse_harness,
)
from band_wezterm.osc import OscKey, emit_many_to_stdout, emit_to_stdout


def announce(agent_id: str, name: str, harness: str | None) -> None:
    """OSC identity into this pane (stdout = WezTerm PTY)."""
    fields: dict[OscKey, str] = {
        OscKey.AGENT_ID: agent_id,
        OscKey.AGENT_NAME: name,
        OscKey.AGENT_INITIALS: initials(name),
        OscKey.AGENT_COLOR: agent_accent(agent_id),
        OscKey.AGENT_KIND: AvatarKind.AGENT.value,
        OscKey.AGENT_STATUS: AgentStatus.ONLINE.value,
        OscKey.AGENT_RUNTIME: AgentRuntime.STARTING.value,
    }
    parsed = parse_harness(harness)
    if parsed is not None:
        fields[OscKey.AGENT_HARNESS] = harness_badge(parsed).value
    emit_many_to_stdout(fields)


def _read_api_key(key_file: Path | None) -> str:
    if key_file is not None:
        key = key_file.read_text(encoding="utf-8").strip()
        try:
            key_file.unlink(missing_ok=True)
        except OSError:
            pass
        if key:
            return key
    env_key = os.environ.get(AGENT_API_KEY_ENV, "").strip()
    if not env_key:
        raise SystemExit(
            "Managed agent API key missing — re-register the agent from Control."
        )
    return env_key


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.agent")
    parser.add_argument("--agent-id", default=os.environ.get(AGENT_ID_ENV, ""))
    parser.add_argument("--harness", default=os.environ.get(AGENT_HARNESS_ENV, ""))
    parser.add_argument("--name", default=os.environ.get(AGENT_NAME_ENV, ""))
    parser.add_argument("--key-file", type=Path, default=None)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    agent_id = args.agent_id.strip()
    name = (args.name or agent_id).strip() or agent_id
    harness = args.harness.strip() or None
    if not agent_id:
        print("BAND_AGENT_ID / --agent-id is required", file=sys.stderr)
        return 2

    announce(agent_id, name, harness)
    api_key = _read_api_key(args.key_file)
    settings = load_settings()
    adapter = build_adapter(harness, cwd=args.cwd)
    config = AgentConfig(auto_subscribe_existing_rooms=True, single_instance=True)

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        rest_url=settings.band_base_url,
        ws_url=settings.band_ws_url,
        config=config,
    )
    emit_to_stdout(OscKey.AGENT_RUNTIME, AgentRuntime.RUNNING.value)
    try:
        async with agent:
            await agent.run_forever()
    except Exception as error:
        emit_to_stdout(OscKey.AGENT_RUNTIME, AgentRuntime.ERROR.value)
        print(f"Agent runtime failed: {error}", file=sys.stderr)
        return 1
    finally:
        emit_to_stdout(OscKey.AGENT_RUNTIME, AgentRuntime.STOPPING.value)
        emit_to_stdout(OscKey.AGENT_STATUS, AgentStatus.OFFLINE.value)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))
