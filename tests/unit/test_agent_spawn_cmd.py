"""Agent pane spawn argv — secrets via key-file, never argv."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from band_wezterm.agent.opencode_server import OpenCodeEndpoint
from band_wezterm.agent.runner import _read_api_key, runtime_banner
from band_wezterm.agent.spawn_cmd import agent_pane_command, write_api_key_file
from band_wezterm.backends import AgentTuning
from band_wezterm.client import AgentRecord
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent
from band_wezterm.managed_profiles import ManagedAgentProfile


def test_runtime_banner_makes_a_running_agent_pane_useful(tmp_path: Path) -> None:
    banner = runtime_banner(
        name="Developer 6753",
        harness="codex",
        tuning=AgentTuning(model="gpt-5.6-sol", reasoning="high"),
        cwd=tmp_path,
    )

    assert "Band agent" in banner
    assert "Agent: Developer 6753" in banner
    assert "Runtime: codex" in banner
    assert "Model: gpt-5.6-sol" in banner
    assert "Reasoning: high" in banner
    assert "Online — listening to Band rooms" in banner
    assert "Read and send messages in Control" in banner


def test_write_api_key_file_is_private() -> None:
    path = write_api_key_file("band_a_secret")
    try:
        assert path.read_text(encoding="utf-8") == "band_a_secret"
        # Windows ACL model ignores POSIX mode bits from chmod.
        if sys.platform != "win32":
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        path.unlink(missing_ok=True)


def test_unreadable_key_file_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "key"
    path.write_text("band_a_secret", encoding="utf-8")

    def fail_read(self: Path, *, encoding: str) -> str:
        if self == path:
            raise OSError("unreadable")
        return Path.read_text(self, encoding=encoding)

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(OSError, match="unreadable"):
        _read_api_key(path)

    assert not path.exists()


def test_agent_pane_command_has_no_api_key_in_argv(tmp_path: Path) -> None:
    agent = AgentRecord(
        id="agent-9",
        name="Omega",
        kind=AvatarKind.AGENT,
        color=agent_accent("agent-9"),
        harness=HarnessId.CODEX,
    )
    key_file = tmp_path / "key"
    key_file.write_text("band_a_secret", encoding="utf-8")
    argv = agent_pane_command(agent, key_file=key_file, cwd=tmp_path)
    joined = " ".join(argv)
    assert "band_a_secret" not in joined
    assert "-m" in argv
    assert "band_wezterm.agent" in argv
    assert "--agent-id" in argv
    assert "agent-9" in argv
    assert "--harness" in argv
    assert "codex" in argv
    assert "--key-file" in argv
    assert str(key_file) in argv


def test_agent_pane_command_includes_persona_and_tuning(tmp_path: Path) -> None:
    agent = AgentRecord(
        id="agent-9",
        name="Omega",
        kind=AvatarKind.AGENT,
        color=agent_accent("agent-9"),
        harness=HarnessId.CLAUDE_SDK,
    )
    key_file = tmp_path / "key"
    key_file.write_text("band_a_secret", encoding="utf-8")
    profile = ManagedAgentProfile(
        agent_id=agent.id,
        name=agent.name,
        harness=HarnessId.CLAUDE_SDK,
        persona="# Developer\n",
        tuning=AgentTuning(model="sonnet", reasoning="off"),
    )
    argv = agent_pane_command(agent, key_file=key_file, cwd=tmp_path, profile=profile)
    assert "--persona-file" in argv
    persona_path = Path(argv[argv.index("--persona-file") + 1])
    assert persona_path.read_text(encoding="utf-8") == "# Developer\n"
    assert "--model" in argv
    assert "sonnet" in argv
    assert "--reasoning" in argv
    assert "low" in argv
    assert "band_a_secret" not in " ".join(argv)


def test_agent_pane_command_prefers_profile_harness(tmp_path: Path) -> None:
    agent = AgentRecord(
        id="agent-9",
        name="Omega",
        kind=AvatarKind.AGENT,
        color=agent_accent("agent-9"),
        harness=HarnessId.CLAUDE_SDK,
    )
    key_file = tmp_path / "key"
    key_file.write_text("band_a_secret", encoding="utf-8")
    profile = ManagedAgentProfile(
        agent_id=agent.id,
        name=agent.name,
        harness=HarnessId.CODEX,
    )
    argv = agent_pane_command(agent, key_file=key_file, cwd=tmp_path, profile=profile)
    assert argv[argv.index("--harness") + 1] == HarnessId.CODEX.value


def test_agent_pane_command_migrates_the_rejected_codex_model_alias(
    tmp_path: Path,
) -> None:
    agent = AgentRecord(
        id="agent-9",
        name="Omega",
        kind=AvatarKind.AGENT,
        color=agent_accent("agent-9"),
        harness=HarnessId.CODEX,
    )
    key_file = tmp_path / "key"
    key_file.write_text("band_a_secret", encoding="utf-8")
    profile = ManagedAgentProfile(
        agent_id=agent.id,
        name=agent.name,
        harness=HarnessId.CODEX,
        tuning=AgentTuning(model="gpt-5.6"),
    )

    argv = agent_pane_command(agent, key_file=key_file, cwd=tmp_path, profile=profile)

    assert argv[argv.index("--model") + 1] == "gpt-5.6-sol"


def test_agent_pane_command_passes_shared_opencode_server(tmp_path: Path) -> None:
    agent = AgentRecord(
        id="agent-9",
        name="Omega",
        kind=AvatarKind.AGENT,
        color=agent_accent("agent-9"),
        harness=HarnessId.OPENCODE,
    )
    profile = ManagedAgentProfile(
        agent_id=agent.id,
        name=agent.name,
        harness=HarnessId.OPENCODE,
    )
    endpoint = OpenCodeEndpoint("http://127.0.0.1:43117")

    argv = agent_pane_command(
        agent,
        key_file=tmp_path / "key",
        cwd=tmp_path,
        profile=profile,
        opencode_endpoint=endpoint,
    )

    assert argv[argv.index("--opencode-server-url") + 1] == endpoint.url
