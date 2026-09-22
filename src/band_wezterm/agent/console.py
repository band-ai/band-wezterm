"""Private native harness console pane entrypoint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from band_wezterm.agent.native_console import (
    exec_native_console,
    read_native_console_launch,
)
from band_wezterm.diagnostics import configure_diagnostics, log_event
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import AgentRuntime
from band_wezterm.pane_identity import announce_agent_pane, announce_runtime_status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.agent.console")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--launch-file", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_diagnostics()
    announce_agent_pane(
        args.agent_id,
        args.name,
        args.harness,
        runtime=AgentRuntime.RUNNING,
    )
    log_event("native console started", agent_id=args.agent_id, harness=args.harness)
    try:
        exec_native_console(read_native_console_launch(args.launch_file))
    except Exception as error:
        message = format_platform_error(error, operation="native console")
        announce_runtime_status(AgentRuntime.ERROR)
        print(f"Native console failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
