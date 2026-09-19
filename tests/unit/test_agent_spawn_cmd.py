"""Agent pane spawn argv — secrets via key-file, never argv."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.agent.spawn_cmd import agent_pane_command, write_api_key_file
from band_wezterm.backends import AgentTuning
from band_wezterm.client import AgentRecord
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent
from band_wezterm.managed_profiles import ManagedAgentProfile


def test_write_api_key_file_is_private() -> None:
    path = write_api_key_file("band_a_secret")
    try:
        assert path.read_text(encoding="utf-8") == "band_a_secret"
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        path.unlink(missing_ok=True)


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
    assert "off" in argv
    assert "band_a_secret" not in " ".join(argv)
