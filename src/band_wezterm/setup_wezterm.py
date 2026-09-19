"""Idempotent WezTerm config wiring for the Band plugin."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from band_wezterm.wezterm_cli import wezterm_bin

WEZTERM_PLUGIN_URL: Final = "https://github.com/band-ai/band-wezterm"
MANAGED_BEGIN: Final = "-- BEGIN BAND-WEZTERM MANAGED"
MANAGED_END: Final = "-- END BAND-WEZTERM MANAGED"
HOME_CONFIG_NAME: Final = ".wezterm.lua"
DEFAULT_CONFIG_DIRNAME: Final = ".config"
XDG_WEZTERM_RELATIVE: Final = Path("wezterm") / "wezterm.lua"
WEZTERM_CONFIG_FILE_ENV: Final = "WEZTERM_CONFIG_FILE"

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

_RETURN_LINE_RE: Final = re.compile(
    r"^([ \t]*)return\b.*$",
    re.MULTILINE,
)
_MANAGED_BLOCK_RE: Final = re.compile(
    r"^[ \t]*"
    + re.escape(MANAGED_BEGIN)
    + r".*?"
    + re.escape(MANAGED_END)
    + r"[ \t]*\r?\n?",
    re.DOTALL | re.MULTILINE,
)
_ORPHAN_BEGIN_RE: Final = re.compile(
    r"^[ \t]*" + re.escape(MANAGED_BEGIN) + r".*$",
    re.MULTILINE,
)
_LEGACY_DOFILE_RE: Final = re.compile(
    r"^[ \t]*dofile\s*\([^\n]*band\.wezterm\.lua[^\n]*\)[ \t]*\r?\n?",
    re.MULTILINE,
)
_CONFIG_BUILDER_RE: Final = re.compile(
    r"^([ \t]*(?:local[ \t]+)?config[ \t]*=[ \t]*wezterm\.config_builder\s*\(\s*\)[^\n]*\r?\n)",
    re.MULTILINE,
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
    """Prefer WezTerm's own config resolution order, else ``~/.wezterm.lua``."""
    env_path = os.environ.get(WEZTERM_CONFIG_FILE_ENV, "").strip()
    if env_path:
        return Path(env_path).expanduser()

    home_dir = home if home is not None else Path.home()
    xdg_config = (
        Path(os.environ["XDG_CONFIG_HOME"])
        if "XDG_CONFIG_HOME" in os.environ
        else home_dir / DEFAULT_CONFIG_DIRNAME
    )
    candidates = (
        home_dir / HOME_CONFIG_NAME,
        xdg_config / XDG_WEZTERM_RELATIVE,
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
        return _create_fresh_config(path)

    current = path.read_text(encoding="utf-8")
    updated = _upsert_managed_block(current)
    if updated == current:
        return SetupResult(path=path, action=SetupAction.UNCHANGED)

    _atomic_write(path, updated)
    return SetupResult(path=path, action=SetupAction.UPDATED)


def _create_fresh_config(path: Path) -> SetupResult:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(_FRESH_CONFIG)
    except FileExistsError:
        current = path.read_text(encoding="utf-8")
        updated = _upsert_managed_block(current)
        if updated == current:
            return SetupResult(path=path, action=SetupAction.UNCHANGED)
        _atomic_write(path, updated)
        return SetupResult(path=path, action=SetupAction.UPDATED)
    return SetupResult(path=path, action=SetupAction.CREATED)


def _atomic_write(path: Path, content: str) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    prior_mode = path.stat().st_mode if path.is_file() else None
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        if prior_mode is not None:
            os.chmod(tmp_path, prior_mode)
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _upsert_managed_block(source: str) -> str:
    cleaned = _LEGACY_DOFILE_RE.sub("", source)
    cleaned = _strip_managed_regions(cleaned)
    return _insert_managed_block(cleaned)


def _strip_managed_regions(source: str) -> str:
    stripped, _count = _MANAGED_BLOCK_RE.subn("", source, count=0)
    return _strip_orphan_begins(stripped)


def _strip_orphan_begins(source: str) -> str:
    while True:
        orphan = _ORPHAN_BEGIN_RE.search(source)
        if orphan is None:
            return source
        start = orphan.start()
        end_match = re.search(re.escape(MANAGED_END), source[orphan.end() :])
        if end_match is not None:
            stop = orphan.end() + end_match.end()
            if stop < len(source) and source[stop] == "\n":
                stop += 1
            source = source[:start] + source[stop:]
            continue
        return_match = _RETURN_LINE_RE.search(source, orphan.end())
        if return_match is not None:
            source = source[:start] + source[return_match.start() :]
            continue
        return source[:start]


def _insert_managed_block(source: str) -> str:
    builder = _CONFIG_BUILDER_RE.search(source)
    if builder is not None:
        rest = source[builder.end() :].lstrip("\n")
        return f"{source[: builder.end()]}\n{_MANAGED_BLOCK}\n{rest}"

    returns = list(_RETURN_LINE_RE.finditer(source))
    top_level = [match for match in returns if not match.group(1)]
    if top_level:
        match = top_level[-1]
        prefix = source[: match.start()].rstrip("\n")
        return f"{prefix}\n{_MANAGED_BLOCK}\n{source[match.start() :]}"

    separator = "" if source.endswith("\n") or source == "" else "\n"
    return f"{source}{separator}\n{_MANAGED_BLOCK}"
