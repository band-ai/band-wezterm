"""Real wezterm-mux-server CLI plumbing (correction #14) — never tab-bar rendering."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from band_wezterm.wezterm_cli import (
    WindowId,
    additional_spawn_args,
    first_spawn_args,
    kill_pane,
    list_panes,
    spawn_additional_tab,
    spawn_first_tab,
    split_pane,
)

pytestmark = pytest.mark.live_wezterm

WEZTERM = shutil.which("wezterm")
MUX_SERVER = shutil.which("wezterm-mux-server")
DEFAULT_MUX_DIR = Path.home() / ".local" / "share" / "wezterm"
DEFAULT_MUX_SOCK = DEFAULT_MUX_DIR / "sock"


def test_first_spawn_args_use_new_window_without_workspace() -> None:
    args = first_spawn_args(Path("/tmp"), ["python", "-m", "band_wezterm.tui"])
    assert "--new-window" in args
    assert "--workspace" not in args
    assert "--window-id" not in args


def test_additional_spawn_args_use_window_id() -> None:
    args = additional_spawn_args(
        WindowId(42), Path("/tmp"), ["sleep", "infinity"]
    )
    assert "--window-id" in args
    assert "42" in args
    assert "--workspace" not in args
    assert "--new-window" not in args


@pytest.fixture
def mux_server() -> Path:
    """Start a real headless mux-server on WezTerm's default socket path.

    Custom ``WEZTERM_UNIX_SOCKET`` paths are ignored by ``wezterm-mux-server``
    in practice — it always binds under ``~/.local/share/wezterm/sock``.
    """
    if WEZTERM is None:
        pytest.skip("wezterm not on PATH")
    if MUX_SERVER is None:
        pytest.skip("wezterm-mux-server not on PATH")

    DEFAULT_MUX_DIR.mkdir(parents=True, exist_ok=True)
    # Prefer a fresh server for this process; if one is already healthy, reuse it.
    if not DEFAULT_MUX_SOCK.exists():
        subprocess.run(
            [MUX_SERVER, "--daemonize", "--skip-config"],
            check=False,
            capture_output=True,
            text=True,
        )
    deadline = time.time() + 5
    while time.time() < deadline and not DEFAULT_MUX_SOCK.exists():
        time.sleep(0.05)
    if not DEFAULT_MUX_SOCK.exists():
        pytest.skip("wezterm-mux-server socket never appeared")
    return DEFAULT_MUX_SOCK


def test_live_spawn_list_kill(mux_server: Path) -> None:
    del mux_server  # fixture side-effect only
    cwd = Path(tempfile.mkdtemp(prefix="band-wezterm-cli-"))
    try:
        first = spawn_first_tab(cwd, ["bash", "-lc", "exec sleep 30"])
    except Exception as exc:
        pytest.skip(f"wezterm spawn unavailable: {exc}")
    try:
        panes = list_panes()
        assert any(p.pane_id == first.pane_id.root for p in panes)
        second = spawn_additional_tab(
            first.window_id, cwd, ["bash", "-lc", "exec sleep 30"]
        )
        panes = list_panes()
        assert any(p.pane_id == second.root for p in panes)
        kill_pane(second)
    finally:
        with contextlib.suppress(Exception):
            kill_pane(first.pane_id)


def test_live_split_keeps_console_and_bridge_in_one_tab(mux_server: Path) -> None:
    del mux_server  # fixture side-effect only
    cwd = Path(tempfile.mkdtemp(prefix="band-wezterm-cli-"))
    try:
        console = spawn_first_tab(cwd, ["bash", "-lc", "exec sleep 30"])
    except Exception as exc:
        pytest.skip(f"wezterm spawn unavailable: {exc}")
    bridge = None
    try:
        bridge = split_pane(console.pane_id, cwd, ["bash", "-lc", "exec sleep 30"])
        pane_ids = {pane.pane_id for pane in list_panes()}
        assert console.pane_id.root in pane_ids
        assert bridge.root in pane_ids
    finally:
        if bridge is not None:
            with contextlib.suppress(Exception):
                kill_pane(bridge)
        with contextlib.suppress(Exception):
            kill_pane(console.pane_id)
