"""Idempotent WezTerm config wiring for the Band plugin."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from band_wezterm.wezterm_cli import wezterm_bin

WEZTERM_PLUGIN_URL: Final = "https://github.com/band-ai/band-wezterm"
MANAGED_BEGIN: Final = "-- BEGIN BAND-WEZTERM MANAGED"
MANAGED_END: Final = "-- END BAND-WEZTERM MANAGED"

_MANAGED_BLOCK: Final = f"""{MANAGED_BEGIN}
do
  local band = wezterm.plugin.require '{WEZTERM_PLUGIN_URL}'
  band.apply_to_config(config)
end
{MANAGED_END}
"""

_FRESH_CONFIG: Final = f"""local wezterm = require 'wezterm'
local config = wezterm.config_builder()

{_MANAGED_BLOCK}
return config
"""

_RETURN_CONFIG_RE: Final = re.compile(
    r"^([ \t]*)return[ \t]+config\b",
    re.MULTILINE,
)
_MANAGED_BLOCK_RE: Final = re.compile(
    re.escape(MANAGED_BEGIN) + r".*?" + re.escape(MANAGED_END) + r"\n?",
    re.DOTALL,
)


class SetupAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class SetupResult:
    path: Path
    action: SetupAction


def resolve_wezterm_config_path(*, home: Path | None = None) -> Path:
    """Prefer an existing WezTerm config; otherwise use ``~/.wezterm.lua``."""
    home_dir = home if home is not None else Path.home()
    xdg_config = Path(os.environ["XDG_CONFIG_HOME"]) if "XDG_CONFIG_HOME" in os.environ else home_dir / ".config"
    candidates = (
        home_dir / ".wezterm.lua",
        xdg_config / "wezterm" / "wezterm.lua",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def ensure_band_plugin_config(*, home: Path | None = None) -> SetupResult:
    """Create or update the managed Band plugin block in the WezTerm config."""
    wezterm_bin()

    path = resolve_wezterm_config_path(home=home)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_FRESH_CONFIG, encoding="utf-8")
        return SetupResult(path=path, action=SetupAction.CREATED)

    current = path.read_text(encoding="utf-8")
    updated = _upsert_managed_block(current)
    if updated == current:
        return SetupResult(path=path, action=SetupAction.UNCHANGED)

    path.write_text(updated, encoding="utf-8")
    return SetupResult(path=path, action=SetupAction.UPDATED)


def _upsert_managed_block(source: str) -> str:
    replaced, count = _MANAGED_BLOCK_RE.subn(_MANAGED_BLOCK, source, count=1)
    if count:
        return replaced

    match = _RETURN_CONFIG_RE.search(source)
    if match is not None:
        indent = match.group(1)
        block = "".join(
            f"{indent}{line}" if line.strip() else line
            for line in _MANAGED_BLOCK.splitlines(keepends=True)
        )
        return source[: match.start()] + block + source[match.start() :]

    separator = "" if source.endswith("\n") or source == "" else "\n"
    return f"{source}{separator}\n{_MANAGED_BLOCK}"
