"""Native harness console construction and isolation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from band_wezterm.agent.native_console import (
    NativeConsoleLaunch,
    NativeConsoleUnavailableError,
    build_native_console,
    exec_native_console,
    preflight_native_console,
    read_native_console_launch,
    write_native_console_launch,
)
from band_wezterm.backends import CODEX_DEFAULT_MODEL, AgentTuning
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile


def profile(
    harness: HarnessId,
    *,
    persona: str | None = "You are concise.",
    model: str = "",
    reasoning: str = "",
) -> ManagedAgentProfile:
    return ManagedAgentProfile(
        agent_id="agent/one",
        name="One",
        harness=harness,
        persona=persona,
        tuning=AgentTuning(model=model, reasoning=reasoning),
    )


def test_codex_console_uses_normalized_profile_without_band_bridge() -> None:
    launch = build_native_console(
        profile(HarnessId.CODEX, model="gpt-5.6", reasoning="high"),
        cwd=Path("/workspace"),
    )

    assert launch.command[:3] == ("codex", "--cd", str(Path("/workspace")))
    assert CODEX_DEFAULT_MODEL in launch.command
    assert "model_reasoning_effort=\"high\"" in launch.command
    assert "developer_instructions=\"You are concise.\"" in launch.command
    assert "band_wezterm.agent" not in launch.command
    assert launch.environment == {}


def test_claude_console_leaves_unsupported_reasoning_to_native_default() -> None:
    launch = build_native_console(
        profile(HarnessId.CLAUDE_SDK, model="sonnet", reasoning="on"),
        cwd=Path("/workspace"),
    )

    assert launch.command == (
        "claude",
        "--model",
        "sonnet",
        "--append-system-prompt",
        "You are concise.",
    )


def test_opencode_console_starts_isolated_tui_instead_of_attaching_band_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    launch = build_native_console(
        profile(HarnessId.OPENCODE, model="provider/model"),
        cwd=Path("/workspace"),
    )

    assert launch.command == ("opencode",)
    assert "attach" not in launch.command
    config_path = Path(launch.environment["OPENCODE_CONFIG"])
    assert json.loads(config_path.read_text(encoding="utf-8"))["model"] == (
        "provider/model"
    )


def test_launch_spec_is_private_and_consumed_once(tmp_path: Path) -> None:
    launch = NativeConsoleLaunch(("codex",), tmp_path, {"KEY": "value"})

    path = write_native_console_launch(launch)

    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert read_native_console_launch(path) == launch
    assert not path.exists()


def test_invalid_launch_spec_is_consumed(tmp_path: Path) -> None:
    path = tmp_path / "launch.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid native console"):
        read_native_console_launch(path)

    assert not path.exists()


def test_preflight_reports_missing_native_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("band_wezterm.agent.native_console.shutil.which", lambda _name: None)

    with pytest.raises(NativeConsoleUnavailableError, match="codex CLI not found"):
        preflight_native_console(HarnessId.CODEX)


def test_exec_native_console_removes_band_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BAND_API_KEY_USER", "secret")
    monkeypatch.setenv("BAND_AGENT_ID", "agent")
    monkeypatch.setenv("OPENAI_API_KEY", "harness-key")
    executed = MagicMock(side_effect=RuntimeError("stop exec"))
    monkeypatch.setattr("band_wezterm.agent.native_console.os.execvpe", executed)

    launch = NativeConsoleLaunch(("codex",), tmp_path, {"CONSOLE_OPTION": "enabled"})
    with pytest.raises(RuntimeError, match="stop exec"):
        exec_native_console(launch)

    environment = executed.call_args.args[2]
    assert not any(key.startswith("BAND_") for key in environment)
    assert environment["OPENAI_API_KEY"] == "harness-key"
    assert environment["CONSOLE_OPTION"] == "enabled"
