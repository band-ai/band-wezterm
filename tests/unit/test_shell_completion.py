"""Generated shell completion remains discoverable by a fresh zsh session."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from band_wezterm.cli import create_app
from band_wezterm.listing import ListQuery


async def _list_rooms(_query: ListQuery) -> int:
    return 0


async def _list_agents(_query: ListQuery, _verbose: bool) -> int:
    return 0


async def _reference_action(_reference: str) -> int:
    return 0


async def _stop_agent(_reference: str | None, _all: bool) -> int:
    return 0


async def _status(_room: bool, _agent: bool) -> int:
    return 0


def _completion_app():
    return create_app(
        setup=lambda: 0,
        room_view=lambda _reference: 0,
        agent_view=lambda _reference: 0,
        create_agent=lambda: 0,
        configure_agent=lambda _reference: 0,
        rooms=_list_rooms,
        agents=_list_agents,
        create_room=_reference_action,
        delete_room=_reference_action,
        delete_agent=_reference_action,
        start_agent=_reference_action,
        stop_agent=_stop_agent,
        agent_status=_reference_action,
        status=_status,
        logs=lambda _tail: 0,
    )


def test_fresh_zsh_registers_the_generated_band_completion(tmp_path: Path) -> None:
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh is not installed")
    completion_path = tmp_path / "_cyclopts_band"
    completion_path.write_text(_completion_app().generate_completion(shell="zsh"))
    command = (
        f"fpath=({completion_path.parent} $fpath); "
        "autoload -Uz compinit; compinit -D; "
        '[[ ${_comps[band]-} = _cyclopts_band ]]'
    )

    result = subprocess.run(
        [zsh, "-dfc", command], capture_output=True, check=False, text=True
    )

    assert result.returncode == 0, result.stderr
