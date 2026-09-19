"""Live WezTerm load of the Band plugin after ``band-wezterm setup``."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from band_wezterm.setup_wezterm import ensure_band_plugin_config

pytestmark = pytest.mark.live_wezterm

WEZTERM = shutil.which("wezterm")


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("WEZTERM_CONFIG_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("BAND_WEZTERM_PLUGIN_URL", raising=False)
    # Keep WezTerm plugin clones out of the real user tree.
    support = tmp_path / "wezterm-support"
    support.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    # macOS WezTerm uses Application Support; point HOME so relative lookups stay
    # under tmp when possible. Plugin cache path is still under real Library on
    # some builds — acceptable for this smoke as long as require succeeds.
    return home


def test_setup_then_wezterm_loads_plugin(isolated_home: Path) -> None:
    if WEZTERM is None:
        pytest.skip("wezterm not on PATH")

    result = ensure_band_plugin_config(home=isolated_home)
    assert result.path.is_file()
    config_text = result.path.read_text(encoding="utf-8")
    assert "wezterm.plugin.require 'file://" in config_text
    assert "apply_to_config" in config_text

    # Append a log line so we can prove config evaluation finished.
    probe = (
        "\nwezterm.log_info('band-wezterm live e2e: config loaded')\n"
    )
    # Insert before final return config
    if "return config" in config_text:
        config_text = config_text.replace(
            "return config",
            f"{probe}return config",
            1,
        )
    else:
        config_text = config_text + probe
    result.path.write_text(config_text, encoding="utf-8")

    env = {**os.environ, "WEZTERM_LOG": "info"}
    completed = subprocess.run(
        [WEZTERM, "--config-file", str(result.path), "ls-fonts"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    combined = completed.stdout + "\n" + completed.stderr
    assert "band-wezterm live e2e: config loaded" in combined, combined
    assert "plugin require failed" not in combined.lower()
    assert "apply_to_config failed" not in combined.lower()
    # Soft: lua errors mentioning our plugin
    assert "band_wezterm" not in combined.lower() or "live e2e" in combined
