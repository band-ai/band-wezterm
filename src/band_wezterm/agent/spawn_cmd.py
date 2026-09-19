"""Build the WezTerm spawn argv for a managed agent pane."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from band_wezterm.client import AgentRecord
from band_wezterm.identity import HarnessId


def write_api_key_file(api_key: str) -> Path:
    """0600 temp file; the agent pane deletes it after reading."""
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="band-wezterm-agent-",
        suffix=".key",
        delete=False,
    )
    with handle:
        path = Path(handle.name)
        path.chmod(0o600)
        handle.write(api_key)
    return path


def agent_pane_command(
    agent: AgentRecord,
    *,
    key_file: Path,
    cwd: Path,
) -> list[str]:
    harness = agent.harness or HarnessId.CLAUDE_SDK
    return [
        sys.executable,
        "-m",
        "band_wezterm.agent",
        "--agent-id",
        agent.id,
        "--harness",
        harness.value,
        "--name",
        agent.name,
        "--key-file",
        str(key_file),
        "--cwd",
        str(cwd),
    ]
