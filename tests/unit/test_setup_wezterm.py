"""WezTerm config setup — managed Band plugin block."""

from __future__ import annotations

from pathlib import Path

import pytest

from band_wezterm.setup_wezterm import (
    HOME_CONFIG_NAME,
    MANAGED_BEGIN,
    MANAGED_END,
    WEZTERM_CONFIG_FILE_ENV,
    WEZTERM_PLUGIN_URL,
    XDG_WEZTERM_RELATIVE,
    SetupAction,
    ensure_band_plugin_config,
    resolve_wezterm_config_path,
)
from band_wezterm.wezterm_cli import WezTermNotFoundError


@pytest.fixture(autouse=True)
def _stub_wezterm_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "band_wezterm.setup_wezterm.wezterm_bin",
        lambda: "/usr/bin/wezterm",
    )


def test_resolve_prefers_existing_home_dotfile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    dot = home / HOME_CONFIG_NAME
    xdg = home / ".config" / XDG_WEZTERM_RELATIVE
    xdg.parent.mkdir(parents=True)
    dot.write_text("-- home\n", encoding="utf-8")
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == dot


def test_resolve_falls_back_to_xdg(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg = home / ".config" / XDG_WEZTERM_RELATIVE
    xdg.parent.mkdir(parents=True)
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == xdg


def test_resolve_honors_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    xdg_root = tmp_path / "xdg"
    target = xdg_root / XDG_WEZTERM_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text("-- xdg home\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_root))
    assert resolve_wezterm_config_path(home=home) == target


def test_resolve_honors_wezterm_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    custom = tmp_path / "custom.lua"
    custom.write_text("-- custom\n", encoding="utf-8")
    monkeypatch.setenv(WEZTERM_CONFIG_FILE_ENV, str(custom))
    assert resolve_wezterm_config_path(home=home) == custom


def test_resolve_defaults_to_home_dotfile_when_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    assert resolve_wezterm_config_path(home=home) == home / HOME_CONFIG_NAME


def test_ensure_creates_fresh_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.CREATED
    assert result.path == home / HOME_CONFIG_NAME
    text = result.path.read_text(encoding="utf-8")
    assert MANAGED_BEGIN in text
    assert MANAGED_END in text
    assert WEZTERM_PLUGIN_URL in text
    assert "wezterm.config_builder()" in text
    assert text.strip().endswith("return config")


def test_ensure_injects_after_config_builder(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "config.font_size = 14\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "config.font_size = 14" in text
    assert text.index("config_builder()") < text.index(MANAGED_BEGIN)
    assert text.index(MANAGED_BEGIN) < text.index("config.font_size")
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = ensure_band_plugin_config(home=home)
    second = ensure_band_plugin_config(home=home)
    assert first.action is SetupAction.CREATED
    assert second.action is SetupAction.UNCHANGED
    text = first.path.read_text(encoding="utf-8")
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_idempotent_after_indented_return(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "\treturn config\n",
        encoding="utf-8",
    )
    first = ensure_band_plugin_config(home=home)
    second = ensure_band_plugin_config(home=home)
    assert first.action is SetupAction.UPDATED
    assert second.action is SetupAction.UNCHANGED
    assert path.read_text(encoding="utf-8").count(MANAGED_BEGIN) == 1


def test_ensure_uses_last_return_not_nested(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local function unused()\n"
        "  return config\n"
        "end\n"
        "config.font_size = 14\n"
        "return {}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) > text.index("config.font_size")
    assert text.index(MANAGED_BEGIN) < text.rindex("return {}")


def test_ensure_injects_before_return_empty_table(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\nreturn {}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) < text.index("return {}")


def test_ensure_updates_stale_managed_block(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "-- stale\n"
        f"{MANAGED_END}\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert WEZTERM_PLUGIN_URL in text
    assert "-- stale" not in text
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_repairs_orphan_begin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "-- broken\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.count(MANAGED_BEGIN) == 1
    assert MANAGED_END in text
    assert "-- broken" not in text


def test_ensure_strips_legacy_dofile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        'dofile("/repo/wezterm/band.wezterm.lua")\n'
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "band.wezterm.lua" not in text
    assert MANAGED_BEGIN in text


def test_ensure_requires_wezterm_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()

    def _missing() -> str:
        raise WezTermNotFoundError("wezterm not found on PATH")

    monkeypatch.setattr("band_wezterm.setup_wezterm.wezterm_bin", _missing)
    with pytest.raises(WezTermNotFoundError, match="not found on PATH"):
        ensure_band_plugin_config(home=home)


def test_ensure_strips_orphan_after_complete_block(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "do end\n"
        f"{MANAGED_END}\n"
        f"{MANAGED_BEGIN}\n"
        "-- orphan junk\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.count(MANAGED_BEGIN) == 1
    assert "-- orphan junk" not in text


def test_ensure_injects_after_crlf_config_builder(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_bytes(
        b"local wezterm = require 'wezterm'\r\n"
        b"local config = wezterm.config_builder()\r\n"
        b"wezterm.on('format-tab-title', function() end)\r\n"
        b"return config\r\n"
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) < text.index("format-tab-title")


def test_ensure_injects_after_non_local_config_builder(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "config = wezterm.config_builder()\n"
        "wezterm.on('format-tab-title', function() end)\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) < text.index("format-tab-title")


def test_ensure_preserves_file_mode(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "return config\n",
        encoding="utf-8",
    )
    path.chmod(0o644)
    ensure_band_plugin_config(home=home)
    assert (path.stat().st_mode & 0o777) == 0o644


def test_ensure_appends_when_only_nested_return(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local function f()\n"
        "  return 1\n"
        "end\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index("end") < text.index(MANAGED_BEGIN)
