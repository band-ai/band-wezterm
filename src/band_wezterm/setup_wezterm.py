"""Idempotent WezTerm config wiring for the Band plugin."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from band_wezterm.wezterm_cli import WezTermNotFoundError

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


def require_wezterm_on_path() -> str:
    """Return the ``wezterm`` binary path or raise ``WezTermNotFoundError``."""
    path = shutil.which("wezterm")
    if path is None:
        raise WezTermNotFoundError(
            "wezterm not found on PATH — install WezTerm first "
            "(e.g. `brew install --cask wezterm`)"
        )
    return path


def resolve_wezterm_config_path(*, home: Path | None = None) -> Path:
    """Prefer an existing WezTerm config; otherwise use ``~/.wezterm.lua``."""
    home_dir = home if home is not None else Path.home()
    candidates = (
        home_dir / ".wezterm.lua",
        home_dir / ".config" / "wezterm" / "wezterm.lua",
    )
    for path in candidates:
        if path.is_file():
            return path
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        xdg_path = Path(xdg) / "wezterm" / "wezterm.lua"
        if xdg_path.is_file():
            return xdg_path
    return candidates[0]


def ensure_band_plugin_config(
    *,
    home: Path | None = None,
    check_wezterm: bool = True,
) -> SetupResult:
    """Create or update the managed Band plugin block in the WezTerm config."""
    if check_wezterm:
        require_wezterm_on_path()

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
    if _MANAGED_BLOCK_RE.search(source):
        return _MANAGED_BLOCK_RE.sub(_MANAGED_BLOCK, source, count=1)

    match = _RETURN_CONFIG_RE.search(source)
    if match is not None:
        indent = match.group(1)
        indented = _indent_block(_MANAGED_BLOCK, indent)
        return source[: match.start()] + indented + source[match.start() :]

    separator = "" if source.endswith("\n") or source == "" else "\n"
    return f"{source}{separator}\n{_MANAGED_BLOCK}"


def _indent_block(block: str, indent: str) -> str:
    if not indent:
        return block if block.endswith("\n") else f"{block}\n"
    lines = block.splitlines(keepends=True)
    return "".join(f"{indent}{line}" if line.strip() else line for line in lines)
