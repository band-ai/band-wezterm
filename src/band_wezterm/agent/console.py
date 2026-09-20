"""Private native harness console pane entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from band_wezterm.agent.native_console import (
    exec_native_console,
    read_native_console_launch,
)
from band_wezterm.agent.pane_identity import announce_agent_pane
from band_wezterm.identity import AgentRuntime, AgentStatus
from band_wezterm.osc import OscKey, emit_to_stdout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.agent.console")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--launch-file", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    announce_agent_pane(args.agent_id, args.name, args.harness)
    emit_to_stdout(OscKey.AGENT_RUNTIME, AgentRuntime.RUNNING.value)
    try:
        exec_native_console(read_native_console_launch(args.launch_file))
    except Exception as error:
        emit_to_stdout(OscKey.AGENT_RUNTIME, AgentRuntime.ERROR.value)
        emit_to_stdout(OscKey.AGENT_STATUS, AgentStatus.OFFLINE.value)
        print(f"Native console failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
