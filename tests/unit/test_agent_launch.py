"""Unit tests for managed-agent WezTerm launch modes."""

from __future__ import annotations

from pathlib import Path

import pytest

from band_wezterm.agent.launch import (
    AgentLaunchContext,
    attach_interactive_console,
    prepare_agent_launch,
    spawn_agent_panes,
)
from band_wezterm.client import AgentRecord
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.wezterm_cli import PaneId, SplitDirection, WindowId


def _context(
    *, interactive: bool, cwd: Path, focus_pane: PaneId | None = None
) -> AgentLaunchContext:
    agent = AgentRecord(
        id="a1",
        name="Beta",
        kind=AvatarKind.AGENT,
        color=agent_accent("a1"),
        harness=HarnessId.CODEX,
    )
    return AgentLaunchContext(
        agent=agent,
        api_key="band_a_key",
        profile=ManagedAgentProfile(
            agent_id="a1", name="Beta", harness=HarnessId.CODEX
        ),
        window_id=WindowId(42),
        cwd=cwd,
        interactive_console=interactive,
        focus_pane=focus_pane,
    )


@pytest.mark.asyncio
async def test_spawn_static_opens_bridge_tab_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[list[str]] = []

    def fake_spawn(_window: object, _cwd: object, command: list[str]) -> PaneId:
        spawned.append(command)
        return PaneId(7)

    monkeypatch.setattr(
        "band_wezterm.agent.launch.spawn_additional_tab", fake_spawn
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.split_pane",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no split")),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_api_key_file",
        lambda _key: tmp_path / "key",
    )
    activated: list[PaneId] = []
    monkeypatch.setattr(
        "band_wezterm.agent.launch.activate_pane", activated.append
    )

    context = _context(
        interactive=False, cwd=tmp_path, focus_pane=PaneId(1)
    )
    resources = prepare_agent_launch(context)
    assert resources.console_command == []
    panes = await spawn_agent_panes(context, resources)
    assert panes.console == PaneId(7)
    assert panes.bridge == PaneId(7)
    assert len(spawned) == 1
    assert "band_wezterm.agent" in spawned[0]
    assert "band_wezterm.agent.console" not in spawned[0]
    assert activated == [PaneId(1)]


@pytest.mark.asyncio
async def test_spawn_interactive_opens_console_then_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[list[str]] = []
    splits: list[list[str]] = []

    def fake_spawn(_window: object, _cwd: object, command: list[str]) -> PaneId:
        spawned.append(command)
        return PaneId(7)

    def fake_split(_pane: object, _cwd: object, command: list[str]) -> PaneId:
        splits.append(command)
        return PaneId(8)

    monkeypatch.setattr(
        "band_wezterm.agent.launch.spawn_additional_tab", fake_spawn
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr("band_wezterm.agent.launch.split_pane", fake_split)
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_api_key_file",
        lambda _key: tmp_path / "key",
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_native_console_launch",
        lambda _launch: tmp_path / "console.json",
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.build_native_console",
        lambda _profile, *, cwd: object(),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.native_console_command",
        lambda **_kwargs: ["python", "-m", "band_wezterm.agent.console"],
    )

    activated: list[PaneId] = []
    monkeypatch.setattr(
        "band_wezterm.agent.launch.activate_pane", activated.append
    )

    context = _context(
        interactive=True, cwd=tmp_path, focus_pane=PaneId(1)
    )
    resources = prepare_agent_launch(context)
    panes = await spawn_agent_panes(context, resources)
    assert panes.console == PaneId(7)
    assert panes.bridge == PaneId(8)
    assert "band_wezterm.agent.console" in spawned[0]
    assert "band_wezterm.agent" in splits[0]
    assert activated == [PaneId(1)]


@pytest.mark.asyncio
async def test_spawn_skips_focus_restore_without_control_pane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "band_wezterm.agent.launch.spawn_additional_tab",
        lambda *_a, **_k: PaneId(7),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_api_key_file",
        lambda _key: tmp_path / "key",
    )
    activated: list[PaneId] = []
    monkeypatch.setattr("band_wezterm.agent.launch.activate_pane", activated.append)

    context = _context(interactive=False, cwd=tmp_path)
    await spawn_agent_panes(context, prepare_agent_launch(context))
    assert activated == []


@pytest.mark.asyncio
async def test_attach_interactive_console_splits_above_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    splits: list[tuple[object, ...]] = []
    activated: list[PaneId] = []

    def fake_split(
        pane_id: object,
        cwd: object,
        command: list[str],
        *,
        percent: int,
        direction: SplitDirection,
    ) -> PaneId:
        splits.append((pane_id, cwd, command, percent, direction))
        return PaneId(8)

    monkeypatch.setattr("band_wezterm.agent.launch.split_pane", fake_split)
    monkeypatch.setattr(
        "band_wezterm.agent.launch.activate_pane", activated.append
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.build_native_console",
        lambda _profile, *, cwd: object(),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_native_console_launch",
        lambda _launch: tmp_path / "console.json",
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.native_console_command",
        lambda **_kwargs: ["python", "-m", "band_wezterm.agent.console"],
    )

    context = _context(
        interactive=False, cwd=tmp_path, focus_pane=PaneId(1)
    )
    console = await attach_interactive_console(
        agent=context.agent,
        profile=context.profile,
        bridge=PaneId(7),
        cwd=tmp_path,
        focus_pane=PaneId(1),
    )
    assert console == PaneId(8)
    assert len(splits) == 1
    pane_id, _cwd, command, percent, direction = splits[0]
    assert pane_id == PaneId(7)
    assert "band_wezterm.agent.console" in command
    assert percent == 80
    assert direction is SplitDirection.TOP
    assert activated == [PaneId(1)]
