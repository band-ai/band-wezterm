"""Private native harness consoles for managed agent tabs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from band_wezterm.agent.private_files import write_private_text
from band_wezterm.backends import TuningDimensionId, normalize_tuning
from band_wezterm.config import LOCAL_STATE_DIRNAME
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile

_CONSOLE_STATE_DIRNAME: Final = "native-consoles"
_LAUNCH_FILE_PREFIX: Final = "band-wezterm-console-"
_LAUNCH_FILE_SUFFIX: Final = ".json"
_NATIVE_BINARY: Final[dict[HarnessId, str]] = {
    HarnessId.CLAUDE: "claude",
    HarnessId.CLAUDE_SDK: "claude",
    HarnessId.CODEX: "codex",
    HarnessId.COPILOT: "copilot",
    HarnessId.COPILOT_SDK: "copilot",
    HarnessId.OMP: "opencode",
    HarnessId.OPENCODE: "opencode",
}
_BAND_ENV_PREFIX: Final = "BAND_"
_PREFLIGHT_TIMEOUT_SECONDS: Final = 10
_MISE_VERSION_MISSING: Final = "No version is set for shim"
_MISE_INSTALL_HINTS: Final[dict[str, str]] = {
    "opencode": "mise use -g aqua:anomalyco/opencode@latest",
}


class NativeConsoleUnavailableError(RuntimeError):
    """Raised when the configured native harness CLI cannot start."""


@dataclass(frozen=True)
class NativeConsoleLaunch:
    """A private native CLI invocation; never contains Band credentials."""

    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]


def build_native_console(
    profile: ManagedAgentProfile, *, cwd: Path
) -> NativeConsoleLaunch:
    """Build one private native session from the durable managed profile."""
    normalized = profile.model_copy(
        update={"tuning": normalize_tuning(profile.harness, profile.tuning)}
    )
    return _native_console_for(normalized, cwd=cwd)


def preflight_native_console(harness: HarnessId) -> None:
    """Verify the native CLI, not just the adapter extra, before spawning a tab."""
    binary = _NATIVE_BINARY[harness]
    resolved = shutil.which(binary)
    if resolved is None:
        raise NativeConsoleUnavailableError(
            f"Native {binary} CLI not found on PATH; install and authenticate it first."
        )
    try:
        completed = subprocess.run(
            [resolved, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_PREFLIGHT_TIMEOUT_SECONDS,
        )
    except OSError as error:
        raise NativeConsoleUnavailableError(
            f"Could not start native {binary} CLI: {error}."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise NativeConsoleUnavailableError(
            "Native "
            f"{binary} CLI did not answer `--version` within "
            f"{_PREFLIGHT_TIMEOUT_SECONDS} seconds."
        ) from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise NativeConsoleUnavailableError(
            _native_cli_failure_message(binary, detail)
        )


def _native_cli_failure_message(binary: str, detail: str) -> str:
    if _MISE_VERSION_MISSING in detail:
        install_hint = _MISE_INSTALL_HINTS.get(binary)
        next_step = (
            f"Install it with `{install_hint}`"
            if install_hint is not None
            else "Select an installed version with mise"
        )
        return (
            f"Native {binary} CLI is managed by mise but has no selected version. "
            f"{next_step}, then Start again."
        )
    return f"Native {binary} CLI is unavailable: {detail or 'unknown error'}"


def write_native_console_launch(launch: NativeConsoleLaunch) -> Path:
    """Write a short-lived private launch specification for the console wrapper."""
    payload = {
        "command": list(launch.command),
        "cwd": str(launch.cwd),
        "environment": launch.environment,
    }
    return write_private_text(
        content=json.dumps(payload),
        prefix=_LAUNCH_FILE_PREFIX,
        suffix=_LAUNCH_FILE_SUFFIX,
    )


def read_native_console_launch(path: Path) -> NativeConsoleLaunch:
    """Consume a launch specification exactly once."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    finally:
        path.unlink(missing_ok=True)
    if not isinstance(payload, dict):
        raise ValueError("Invalid native console launch specification.")
    command = payload.get("command")
    environment = payload.get("environment")
    cwd = payload.get("cwd")
    if (
        not isinstance(command, list)
        or not all(isinstance(item, str) for item in command)
        or not command
        or not isinstance(environment, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in environment.items()
        )
        or not isinstance(cwd, str)
    ):
        raise ValueError("Invalid native console launch specification.")
    return NativeConsoleLaunch(
        command=tuple(command), cwd=Path(cwd), environment=environment
    )


def native_console_command(
    *, agent_id: str, name: str, harness: HarnessId, launch_file: Path
) -> list[str]:
    """Run the wrapper that announces pane identity then execs the native TUI."""
    return [
        sys.executable,
        "-m",
        "band_wezterm.agent.console",
        "--agent-id",
        agent_id,
        "--name",
        name,
        "--harness",
        harness.value,
        "--launch-file",
        str(launch_file),
    ]


def _native_console_for(
    profile: ManagedAgentProfile, *, cwd: Path
) -> NativeConsoleLaunch:
    match profile.harness:
        case HarnessId.CLAUDE | HarnessId.CLAUDE_SDK:
            return _claude_console(profile, cwd=cwd)
        case HarnessId.CODEX:
            return _codex_console(profile, cwd=cwd)
        case HarnessId.COPILOT | HarnessId.COPILOT_SDK:
            return _copilot_console(profile, cwd=cwd)
        case HarnessId.OMP | HarnessId.OPENCODE:
            return _opencode_console(profile, cwd=cwd)


def _claude_console(profile: ManagedAgentProfile, *, cwd: Path) -> NativeConsoleLaunch:
    command = [_NATIVE_BINARY[profile.harness]]
    model = profile.tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        command.extend(["--model", model])
    effort = profile.tuning.value_for(TuningDimensionId.REASONING)
    if effort is not None:
        command.extend(["--effort", effort])
    instructions = profile.runtime_instructions()
    if instructions:
        command.extend(["--append-system-prompt", instructions])
    return NativeConsoleLaunch(tuple(command), cwd, {})


def _codex_console(profile: ManagedAgentProfile, *, cwd: Path) -> NativeConsoleLaunch:
    command = [_NATIVE_BINARY[profile.harness], "--cd", str(cwd)]
    model = profile.tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        command.extend(["--model", model])
    reasoning = profile.tuning.value_for(TuningDimensionId.REASONING)
    if reasoning is not None:
        command.extend(["--config", _toml_assignment("model_reasoning_effort", reasoning)])
    instructions = profile.runtime_instructions()
    if instructions:
        command.extend(
            ["--config", _toml_assignment("developer_instructions", instructions)]
        )
    return NativeConsoleLaunch(tuple(command), cwd, {})


def _copilot_console(profile: ManagedAgentProfile, *, cwd: Path) -> NativeConsoleLaunch:
    command = [_NATIVE_BINARY[profile.harness], "--context", "default"]
    model = profile.tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        command.extend(["--model", model])
    reasoning = profile.tuning.value_for(TuningDimensionId.REASONING)
    if reasoning is not None:
        command.extend(["--reasoning-effort", reasoning])
    environment = _copilot_instruction_environment(profile)
    return NativeConsoleLaunch(tuple(command), cwd, environment)


def _opencode_console(profile: ManagedAgentProfile, *, cwd: Path) -> NativeConsoleLaunch:
    environment = _opencode_environment(profile)
    command = [_NATIVE_BINARY[profile.harness]]
    return NativeConsoleLaunch(tuple(command), cwd, environment)


def _copilot_instruction_environment(profile: ManagedAgentProfile) -> dict[str, str]:
    instructions = profile.runtime_instructions()
    if not instructions:
        return {}
    directory = _console_profile_directory(profile.agent_id, "copilot")
    _write_console_profile_file(directory / "AGENTS.md", instructions)
    return {"COPILOT_CUSTOM_INSTRUCTIONS_DIRS": str(directory)}


def _opencode_environment(profile: ManagedAgentProfile) -> dict[str, str]:
    instructions = profile.runtime_instructions()
    model = profile.tuning.value_for(TuningDimensionId.MODEL)
    variant = profile.tuning.value_for(TuningDimensionId.REASONING)
    if not instructions and model is None:
        return {}
    directory = _console_profile_directory(profile.agent_id, "opencode")
    persona_path = directory / "persona.md"
    if instructions:
        _write_console_profile_file(persona_path, instructions)
    config: dict[str, object] = {"$schema": "https://opencode.ai/config.json"}
    if model is not None:
        config["model"] = model
        if variant is not None:
            config["agent"] = {
                "build": {"model": model, "variant": variant},
            }
    if instructions:
        config["instructions"] = [str(persona_path)]
    config_path = directory / "opencode.json"
    _write_console_profile_file(config_path, json.dumps(config, indent=2) + "\n")
    return {"OPENCODE_CONFIG": str(config_path)}


def _console_profile_directory(agent_id: str, harness: str) -> Path:
    safe_id = (
        "".join(char if char.isalnum() or char in "-_" else "_" for char in agent_id)
        or "agent"
    )
    return Path.home() / LOCAL_STATE_DIRNAME / _CONSOLE_STATE_DIRNAME / harness / safe_id


def _write_console_profile_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _toml_assignment(key: str, value: str) -> str:
    """JSON strings are valid TOML basic strings for our scalar overrides."""
    return f"{key}={json.dumps(value)}"


def exec_native_console(launch: NativeConsoleLaunch) -> None:
    """Replace the wrapper process with the native TUI after identity is emitted."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(_BAND_ENV_PREFIX)
    }
    environment.update(launch.environment)
    os.chdir(launch.cwd)
    os.execvpe(launch.command[0], list(launch.command), environment)
