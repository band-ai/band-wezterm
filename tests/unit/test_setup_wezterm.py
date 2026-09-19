"""WezTerm config setup — managed Band plugin block."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from band_wezterm.setup_wezterm import (
    HOME_CONFIG_NAME,
    MANAGED_BEGIN,
    MANAGED_END,
    WEZTERM_CONFIG_FILE_ENV,
    WEZTERM_PLUGIN_URL,
    XDG_CONFIG_HOME_ENV,
    XDG_WEZTERM_RELATIVE,
    SetupAction,
    SetupConfigError,
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


@pytest.fixture(autouse=True)
def _clear_wezterm_path_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WEZTERM_CONFIG_FILE_ENV, raising=False)


def test_resolve_prefers_existing_home_dotfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(XDG_CONFIG_HOME_ENV, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    dot = home / HOME_CONFIG_NAME
    xdg = home / ".config" / XDG_WEZTERM_RELATIVE
    xdg.parent.mkdir(parents=True)
    dot.write_text("-- home\n", encoding="utf-8")
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == dot


def test_resolve_falls_back_to_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(XDG_CONFIG_HOME_ENV, raising=False)
    home = tmp_path / "home"
    xdg = home / ".config" / XDG_WEZTERM_RELATIVE
    xdg.parent.mkdir(parents=True)
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == xdg


def test_resolve_home_ignores_ambient_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    ambient = tmp_path / "ambient-xdg"
    ambient_target = ambient / XDG_WEZTERM_RELATIVE
    ambient_target.parent.mkdir(parents=True)
    ambient_target.write_text("-- ambient\n", encoding="utf-8")
    home_xdg = home / ".config" / XDG_WEZTERM_RELATIVE
    home_xdg.parent.mkdir(parents=True)
    home_xdg.write_text("-- home xdg\n", encoding="utf-8")
    monkeypatch.setenv(XDG_CONFIG_HOME_ENV, str(ambient))
    assert resolve_wezterm_config_path(home=home) == home_xdg


def test_resolve_honors_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    xdg_root = tmp_path / "xdg"
    target = xdg_root / XDG_WEZTERM_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text("-- xdg home\n", encoding="utf-8")
    monkeypatch.setenv(XDG_CONFIG_HOME_ENV, str(xdg_root))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert resolve_wezterm_config_path(home=None) == target


def test_resolve_honors_wezterm_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    custom = tmp_path / "custom.lua"
    custom.write_text("-- custom\n", encoding="utf-8")
    monkeypatch.setenv(WEZTERM_CONFIG_FILE_ENV, str(custom))
    assert resolve_wezterm_config_path(home=home) == custom.resolve()


def test_resolve_absolutizes_relative_wezterm_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    custom = tmp_path / "custom.lua"
    custom.write_text("-- custom\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(WEZTERM_CONFIG_FILE_ENV, "custom.lua")
    assert resolve_wezterm_config_path(home=home) == custom.resolve()


def test_resolve_defaults_to_home_dotfile_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(XDG_CONFIG_HOME_ENV, raising=False)
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
    block = text[text.index(MANAGED_BEGIN) : text.index(MANAGED_END)]
    assert "local wezterm = require 'wezterm'" in block
    assert "wezterm.plugin.require" in block
    assert text.strip().endswith("return config")


def test_ensure_managed_block_self_contains_wezterm(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wt = require 'wezterm'\n"
        "local config = wt.config_builder()\n"
        "return config\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    block_start = text.index(MANAGED_BEGIN)
    block_end = text.index(MANAGED_END)
    block = text[block_start:block_end]
    assert "local wezterm = require 'wezterm'" in block
    assert "wezterm.plugin.require" in block


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
    # No builder: inject after require so handlers/body stay after the block.
    assert text.index("require 'wezterm'") < text.index(MANAGED_BEGIN)
    assert text.index(MANAGED_BEGIN) < text.index("config.font_size")
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


def test_ensure_orphan_begin_preserves_trailing_lines(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "config.font_size = 14\n"
        "config.color_scheme = 'Adventure'\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "config.font_size = 14" in text
    assert "config.color_scheme = 'Adventure'" in text
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_malformed_begin_return_end_keeps_return(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "return config\n"
        f"{MANAGED_END}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "return config" in text
    assert text.count(MANAGED_BEGIN) == 1
    assert MANAGED_END in text


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


def test_ensure_rejects_directory_config_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / HOME_CONFIG_NAME).mkdir()
    with pytest.raises(SetupConfigError, match="not a file"):
        ensure_band_plugin_config(home=home)


def test_ensure_empty_file_gets_fresh_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text("   \n\t\n", encoding="utf-8")
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.CREATED
    text = path.read_text(encoding="utf-8")
    assert "wezterm.config_builder()" in text
    assert MANAGED_BEGIN in text
    assert text.strip().endswith("return config")


def test_ensure_preserves_symlink(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "real-wezterm.lua"
    target.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "return config\n",
        encoding="utf-8",
    )
    link = home / HOME_CONFIG_NAME
    link.symlink_to(target)
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    assert link.is_symlink()
    text = target.read_text(encoding="utf-8")
    assert MANAGED_BEGIN in text
    assert MANAGED_END in text


def test_ensure_strips_orphan_after_complete_block(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "do\n"
        "  local band = wezterm.plugin.require 'https://example.invalid'\n"
        "  band.apply_to_config(config)\n"
        "end\n"
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


def test_ensure_injects_before_format_tab_title_without_builder(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "wezterm.on('format-tab-title', function() end)\n"
        "return {}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) < text.index("format-tab-title")


def test_ensure_skips_commented_config_builder(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "--[[\n"
        "local config = wezterm.config_builder()\n"
        "]]\n"
        "wezterm.on('format-tab-title', function() end)\n"
        "return {}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) < text.index("format-tab-title")
    comment_open = text.index("--[[")
    comment_close = text.index("]]")
    managed = text.index(MANAGED_BEGIN)
    assert not (comment_open < managed < comment_close)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
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
    path.chmod(0o600)
    ensure_band_plugin_config(home=home)
    assert (path.stat().st_mode & 0o777) == 0o600


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
    assert text.index("require 'wezterm'") < text.index(MANAGED_BEGIN)
    assert text.index(MANAGED_BEGIN) < text.index("local function f()")


def test_ensure_skips_commented_require(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "--[[\n"
        "local wezterm = require 'wezterm'\n"
        "]]\n"
        "local wezterm = require 'wezterm'\n"
        "wezterm.on('format-tab-title', function() end)\n"
        "return {}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    comment_open = text.index("--[[")
    comment_close = text.index("]]")
    managed = text.index(MANAGED_BEGIN)
    assert not (comment_open < managed < comment_close)
    live_require = text.index("require 'wezterm'", comment_close)
    assert live_require < managed
    assert managed < text.index("format-tab-title")


def test_ensure_orphan_only_file_gets_fresh_scaffold(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(f"{MANAGED_BEGIN}\n", encoding="utf-8")
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "wezterm.config_builder()" in text
    assert text.strip().endswith("return config")
    assert text.count(MANAGED_BEGIN) == 1


def test_ensure_malformed_begin_indented_return_end_keeps_return(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        f"{MANAGED_BEGIN}\n"
        "\treturn config\n"
        f"{MANAGED_END}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "return config" in text
    assert text.count(MANAGED_BEGIN) == 1
    assert MANAGED_END in text


def test_ensure_injects_before_return_when_no_builder_or_require(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text("local config = {}\nreturn config\n", encoding="utf-8")
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index("local config") < text.index(MANAGED_BEGIN)
    assert text.index(MANAGED_BEGIN) < text.index("return config")


def test_ensure_injects_before_on_handler_without_builder_or_require(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "wezterm.on('format-tab-title', function() end)\nreturn {}\n",
        encoding="utf-8",
    )
    result = ensure_band_plugin_config(home=home)
    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert text.index(MANAGED_BEGIN) < text.index("format-tab-title")
    assert text.index(MANAGED_BEGIN) < text.index("return {}")


def test_ensure_rejects_broken_symlink(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    missing = tmp_path / "missing-wezterm.lua"
    link = home / HOME_CONFIG_NAME
    link.symlink_to(missing)
    with pytest.raises(SetupConfigError, match="broken symlink"):
        ensure_band_plugin_config(home=home)
    assert link.is_symlink()
    assert not link.exists()
