"""WezTerm config setup — managed Band plugin block."""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from pathlib import Path
from unittest.mock import patch

import pytest

from band_wezterm.config import LOCAL_STATE_DIRNAME
from band_wezterm.setup_wezterm import (
    BAND_WEZTERM_PLUGIN_URL_ENV,
    DEFAULT_CONFIG_DIRNAME,
    EXAMPLE_HTTPS_PLUGIN_URL,
    GIT_COMMIT_GPGSIGN_FALSE,
    HOME_CONFIG_NAME,
    MANAGED_BEGIN,
    MANAGED_END,
    PLUGIN_DIRNAME,
    PLUGIN_INIT_NAME,
    PLUGIN_INIT_REPO_PATH,
    PLUGIN_LOCK_SUFFIX,
    PLUGIN_REPO_DIRNAME,
    WEZTERM_CONFIG_FILE_ENV,
    XDG_CONFIG_HOME_ENV,
    XDG_WEZTERM_RELATIVE,
    SetupAction,
    SetupConfigError,
    ensure_band_plugin_config,
    materialize_plugin_repo,
    resolve_plugin_require_url,
    resolve_wezterm_config_path,
)
from band_wezterm.wezterm_cli import WezTermNotFoundError

CONCURRENT_MATERIALIZATION_CALLS = 8
LOCK_HOLDER_POLL_ATTEMPTS = 20
LOCK_HOLDER_POLL_SECONDS = 0.05
LOCK_HOLDER_SLEEP_SECONDS = 60


def _materialize_plugin_repo(home: Path) -> Path:
    return materialize_plugin_repo(home=home)


def _remove_readonly_path(
    function: Callable[[str], object], path: str, _error: BaseException
) -> None:
    Path(path).chmod(stat.S_IWRITE)
    function(path)


@pytest.fixture(autouse=True)
def _stub_wezterm_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "band_wezterm.setup_wezterm.wezterm_bin",
        lambda: "/usr/bin/wezterm",
    )
    monkeypatch.delenv(BAND_WEZTERM_PLUGIN_URL_ENV, raising=False)
    monkeypatch.delenv(WEZTERM_CONFIG_FILE_ENV, raising=False)


def test_resolve_prefers_existing_home_dotfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(XDG_CONFIG_HOME_ENV, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    dot = home / HOME_CONFIG_NAME
    xdg = home / DEFAULT_CONFIG_DIRNAME / XDG_WEZTERM_RELATIVE
    xdg.parent.mkdir(parents=True)
    dot.write_text("-- home\n", encoding="utf-8")
    xdg.write_text("-- xdg\n", encoding="utf-8")
    assert resolve_wezterm_config_path(home=home) == dot


def test_resolve_falls_back_to_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(XDG_CONFIG_HOME_ENV, raising=False)
    home = tmp_path / "home"
    xdg = home / DEFAULT_CONFIG_DIRNAME / XDG_WEZTERM_RELATIVE
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
    home_xdg = home / DEFAULT_CONFIG_DIRNAME / XDG_WEZTERM_RELATIVE
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
    assert "wezterm.plugin.require 'file://" in text
    assert "wezterm.config_builder()" in text
    plugin_repo = home / LOCAL_STATE_DIRNAME / PLUGIN_REPO_DIRNAME
    assert (plugin_repo / PLUGIN_DIRNAME / PLUGIN_INIT_NAME).is_file()
    assert (plugin_repo / ".git").is_dir()
    require_url = resolve_plugin_require_url(home=home)
    assert require_url == plugin_repo.as_uri()
    assert f"wezterm.plugin.require '{require_url}'" in text
    block = text[text.index(MANAGED_BEGIN) : text.index(MANAGED_END)]
    assert "local wezterm = require 'wezterm'" in block
    assert "wezterm.plugin.require" in block
    assert text.strip().endswith("return config")


def test_ensure_repairs_a_comment_only_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text("-- Personal WezTerm styling\n", encoding="utf-8")

    result = ensure_band_plugin_config(home=home)

    assert result.action is SetupAction.UPDATED
    text = path.read_text(encoding="utf-8")
    assert "local config = wezterm.config_builder()" in text
    assert "-- Personal WezTerm styling" in text
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
    assert "wezterm.plugin.require 'file://" in text
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


def test_ensure_skips_equals_delimited_commented_config_builder(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / HOME_CONFIG_NAME
    path.write_text(
        "--[=[\n"
        "local config = wezterm.config_builder()\n"
        "]=]\n"
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "return config\n",
        encoding="utf-8",
    )
    ensure_band_plugin_config(home=home)
    text = path.read_text(encoding="utf-8")
    assert text.index("]=]") < text.index(MANAGED_BEGIN)


def test_ensure_escapes_plugin_url_in_lua_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    plugin_url = "file:///tmp/O'Brien/plugin"
    monkeypatch.setenv(BAND_WEZTERM_PLUGIN_URL_ENV, plugin_url)
    result = ensure_band_plugin_config(home=home)
    assert "wezterm.plugin.require 'file:///tmp/O\\'Brien/plugin'" in result.path.read_text(
        encoding="utf-8"
    )


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


def test_resolve_plugin_url_honors_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BAND_WEZTERM_PLUGIN_URL_ENV, EXAMPLE_HTTPS_PLUGIN_URL)
    assert (
        resolve_plugin_require_url(home=tmp_path / "home") == EXAMPLE_HTTPS_PLUGIN_URL
    )


def test_materialize_plugin_repo_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = materialize_plugin_repo(home=home)
    second = materialize_plugin_repo(home=home)
    assert first == second
    init_lua = first / PLUGIN_DIRNAME / PLUGIN_INIT_NAME
    assert "apply_to_config" in init_lua.read_text(encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=first,
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip()


def test_materialize_ignores_untracked_junk(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = materialize_plugin_repo(home=home)
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (root / ".DS_Store").write_bytes(b"\0")

    second = materialize_plugin_repo(home=home)
    assert second == root
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert after == before
    assert (root / ".DS_Store").is_file()


def test_materialize_commits_when_plugin_missing_from_head(tmp_path: Path) -> None:
    """Empty HEAD without tracked plugin/init.lua must rematerialize and commit."""
    home = tmp_path / "home"
    home.mkdir()
    root = home / LOCAL_STATE_DIRNAME / PLUGIN_REPO_DIRNAME
    root.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "--allow-empty",
            "-m",
            "empty",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    missing = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{PLUGIN_INIT_REPO_PATH}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    assert missing.returncode != 0

    materialize_plugin_repo(home=home)
    subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{PLUGIN_INIT_REPO_PATH}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    assert "apply_to_config" in (
        root / PLUGIN_DIRNAME / PLUGIN_INIT_NAME
    ).read_text(encoding="utf-8")


def test_materialize_commit_excludes_staged_ds_store(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = materialize_plugin_repo(home=home)
    (root / ".DS_Store").write_bytes(b"\0")
    subprocess.run(
        ["git", "add", "-f", ".DS_Store"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    init_lua = root / PLUGIN_DIRNAME / PLUGIN_INIT_NAME
    init_lua.write_text("-- stale packaged lua\n", encoding="utf-8")

    materialize_plugin_repo(home=home)
    tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert PLUGIN_INIT_REPO_PATH in tracked
    assert ".DS_Store" not in tracked
    assert "apply_to_config" in init_lua.read_text(encoding="utf-8")


def test_materialize_missing_git_raises(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    def _no_git(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError(2, "No such file or directory", "git")

    with (
        patch("band_wezterm.setup_wezterm.subprocess.run", side_effect=_no_git),
        pytest.raises(SetupConfigError, match="git is required"),
    ):
        materialize_plugin_repo(home=home)


def test_materialize_rewrites_when_content_changes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = materialize_plugin_repo(home=home)
    init_lua = root / PLUGIN_DIRNAME / PLUGIN_INIT_NAME
    init_lua.write_text("-- stale packaged lua\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", f"{PLUGIN_DIRNAME}/{PLUGIN_INIT_NAME}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "-m",
            "stale",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    materialize_plugin_repo(home=home)
    text = init_lua.read_text(encoding="utf-8")
    assert "apply_to_config" in text
    assert "-- stale packaged lua" not in text
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert after != before


def test_materialize_recreates_git_when_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = materialize_plugin_repo(home=home)
    init_text = (root / PLUGIN_DIRNAME / PLUGIN_INIT_NAME).read_text(encoding="utf-8")
    shutil.rmtree(root / ".git", onexc=_remove_readonly_path)
    assert not (root / ".git").exists()

    materialize_plugin_repo(home=home)
    assert (root / ".git").is_dir()
    assert (root / PLUGIN_DIRNAME / PLUGIN_INIT_NAME).read_text(
        encoding="utf-8"
    ) == init_text
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip()


def test_materialize_serializes_concurrent_setup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with ThreadPoolExecutor(max_workers=CONCURRENT_MATERIALIZATION_CALLS) as executor:
        roots = list(
            executor.map(
                _materialize_plugin_repo,
                repeat(home, CONCURRENT_MATERIALIZATION_CALLS),
            )
        )
    expected_root = (home / LOCAL_STATE_DIRNAME / PLUGIN_REPO_DIRNAME).resolve()
    assert set(roots) == {expected_root}
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=roots[0],
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip()


def test_materialize_recovers_after_lock_holder_crashes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = home / LOCAL_STATE_DIRNAME / PLUGIN_REPO_DIRNAME
    lock_path = root.with_name(f".{root.name}{PLUGIN_LOCK_SUFFIX}")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "from filelock import FileLock\n"
                "from pathlib import Path\n"
                "import sys\n"
                "import time\n"
                "with FileLock(Path(sys.argv[1])):\n"
                "    time.sleep(int(sys.argv[2]))\n"
            ),
            str(lock_path),
            str(LOCK_HOLDER_SLEEP_SECONDS),
        ]
    )
    try:
        for _ in range(LOCK_HOLDER_POLL_ATTEMPTS):
            if lock_path.exists():
                break
            time.sleep(LOCK_HOLDER_POLL_SECONDS)
        else:
            pytest.fail("lock holder did not acquire the plugin lock")
        holder.kill()
        holder.wait()
        assert lock_path.exists()
        assert materialize_plugin_repo(home=home) == root
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


def test_materialize_retries_commit_after_failed_commit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = home / LOCAL_STATE_DIRNAME / PLUGIN_REPO_DIRNAME
    plugin_dir = root / PLUGIN_DIRNAME
    plugin_dir.mkdir(parents=True)
    (plugin_dir / PLUGIN_INIT_NAME).write_text("-- placeholder\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", f"{PLUGIN_DIRNAME}/{PLUGIN_INIT_NAME}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    hooks = root / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    pre_commit = hooks / "pre-commit"
    pre_commit.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    pre_commit.chmod(0o755)
    failed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "-m",
            "should fail",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    pre_commit.unlink()
    head_probe = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert head_probe.returncode != 0

    materialize_plugin_repo(home=home)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip()
    assert "apply_to_config" in (plugin_dir / PLUGIN_INIT_NAME).read_text(
        encoding="utf-8"
    )


def test_materialize_commit_disables_gpgsign(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    seen: list[tuple[str, ...]] = []
    real_run = subprocess.run

    def _spy_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = args[0]
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "git":
            seen.append(tuple(str(part) for part in argv))
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    with patch("band_wezterm.setup_wezterm.subprocess.run", side_effect=_spy_run):
        materialize_plugin_repo(home=home)

    commit_argv = next(argv for argv in seen if "commit" in argv)
    assert GIT_COMMIT_GPGSIGN_FALSE in commit_argv
    assert PLUGIN_INIT_REPO_PATH in commit_argv
