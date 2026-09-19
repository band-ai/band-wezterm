"""WezTerm config setup — managed Band plugin block."""

from __future__ import annotations

from pathlib import Path

import pytest

from band_wezterm.setup_wezterm import (
    MANAGED_BEGIN,
    MANAGED_END,
    WEZTERM_PLUGIN_URL,
    SetupAction,
    ensure_band_plugin_config,
    resolve_wezterm_config_path,
)
from band_wezterm.wezterm_cli import WezTermNotFoundError


def test_resolve_prefers_existing_home_dotfile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    dot = home / ".wezterm.lua"
    xdg = home / ".config" / "wezterm" / "wezterm.lua"
    xdg.parent.mkdir(parents=True)
    dot.write_text("-- home\n", encoding="utf-8")
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == dot


def test_resolve_falls_back_to_xdg(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg = home / ".config" / "wezterm" / "wezterm.lua"
    xdg.parent.mkdir(parents=True)
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == xdg


def test_resolve_defaults_to_home_dotfile_when_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    assert resolve_wezterm_config_path(home=home) == home / ".wezterm.lua"


def test_ensure_creates_fresh_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = ensure_band_plugin_config(home=home, check_wezterm=False)
    assert result.action is SetupAction.CREATED
    assert result.path == home / ".wezterm.lua"
    text = result.path.read_text(encoding="utf-8")
    assert MANAGED_BEGIN in text
    assert MANAGED_END in text
    assert WEZTERM_PLUGIN_URL in text
    assert "wezterm.config_builder()" in text
    assert text.strip().endswith("return config")


def test_ensure_injects_before_return_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".wezterm.lua"
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "config.font_size = 14\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home, check_wezterm=False)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "config.font_size = 14" in text
    assert text.index(MANAGED_BEGIN) < text.index("return config")
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = ensure_band_plugin_config(home=home, check_wezterm=False)
    second = ensure_band_plugin_config(home=home, check_wezterm=False)
    assert first.action is SetupAction.CREATED
    assert second.action is SetupAction.UNCHANGED
    text = first.path.read_text(encoding="utf-8")
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_updates_stale_managed_block(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".wezterm.lua"
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "-- stale\n"
        f"{MANAGED_END}\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home, check_wezterm=False)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert WEZTERM_PLUGIN_URL in text
    assert "-- stale" not in text
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_requires_wezterm_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        "band_wezterm.setup_wezterm.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(WezTermNotFoundError, match="not found on PATH"):
        ensure_band_plugin_config(home=home, check_wezterm=True)
