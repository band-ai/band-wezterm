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
XDG_CONFIG_HOME_ENV: Final = "XDG_CONFIG_HOME"
LEGACY_PLUGIN_BASENAME: Final = "band.wezterm.lua"

_MANAGED_BLOCK: Final = f"""{MANAGED_BEGIN}
do
  local wezterm = require 'wezterm'
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
# Canonical managed body only — avoids DOTALL eating a top-level return between
# mismatched BEGIN/END markers.
_MANAGED_BLOCK_RE: Final = re.compile(
    r"^[ \t]*"
    + re.escape(MANAGED_BEGIN)
    + r"\r?\n"
    + r"do\r?\n"
    + r".*?"
    + r"^[ \t]*end\r?\n"
    + r"[ \t]*"
    + re.escape(MANAGED_END)
    + r"[ \t]*\r?\n?",
    re.DOTALL | re.MULTILINE,
)
_ORPHAN_BEGIN_RE: Final = re.compile(
    r"^[ \t]*" + re.escape(MANAGED_BEGIN) + r".*$",
    re.MULTILINE,
)
_LEGACY_DOFILE_RE: Final = re.compile(
    r"^[ \t]*dofile\s*\([^\n]*"
    + re.escape(LEGACY_PLUGIN_BASENAME)
    + r"[^\n]*\)[ \t]*\r?\n?",
    re.MULTILINE,
)
_CONFIG_BUILDER_RE: Final = re.compile(
    r"^([ \t]*(?:local[ \t]+)?config[ \t]*=[ \t]*wezterm\.config_builder\s*\(\s*\)[^\n]*\r?\n)",
    re.MULTILINE,
)
_REQUIRE_WEZTERM_RE: Final = re.compile(
    r"^[ \t]*(?:local[ \t]+\w+[ \t]*=[ \t]*)?require\s*\(?\s*['\"]wezterm['\"].*$",
    re.MULTILINE,
)
_LONG_COMMENT_OPEN: Final = "--[["
_LONG_COMMENT_CLOSE: Final = "]]"


class SetupAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class SetupConfigError(Exception):
    """WezTerm config path exists but cannot be used as a Lua file."""


@dataclass(frozen=True, slots=True)
class SetupResult:
    path: Path
    action: SetupAction


def resolve_wezterm_config_path(*, home: Path | None = None) -> Path:
    """Prefer WezTerm's own config resolution order, else ``~/.wezterm.lua``."""
    env_path = os.environ.get(WEZTERM_CONFIG_FILE_ENV, "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    home_dir = home if home is not None else Path.home()
    # Sandbox XDG when tests (or callers) pass an explicit home.
    if home is not None:
        xdg_config = home_dir / DEFAULT_CONFIG_DIRNAME
    elif XDG_CONFIG_HOME_ENV in os.environ:
        xdg_config = Path(os.environ[XDG_CONFIG_HOME_ENV])
    else:
        xdg_config = home_dir / DEFAULT_CONFIG_DIRNAME
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
    if path.exists() and not path.is_file():
        raise SetupConfigError(f"WezTerm config path is not a file: {path}")
    if not path.is_file():
        return _create_fresh_config(path)
    return _write_upserted(path)


def _create_fresh_config(path: Path) -> SetupResult:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _publish_exclusive(path, _FRESH_CONFIG)
    except FileExistsError:
        return _write_upserted(path)
    return SetupResult(path=path, action=SetupAction.CREATED)


def _write_upserted(path: Path) -> SetupResult:
    current = path.read_text(encoding="utf-8")
    if not current.strip():
        _atomic_write(path, _FRESH_CONFIG)
        return SetupResult(path=path, action=SetupAction.CREATED)

    updated = _upsert_managed_block(current)
    if updated == current:
        return SetupResult(path=path, action=SetupAction.UNCHANGED)

    _atomic_write(path, updated)
    return SetupResult(path=path, action=SetupAction.UPDATED)


def _publish_exclusive(path: Path, content: str) -> None:
    """Write ``content`` to a temp file, then create ``path`` exclusively."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=directory)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            os.link(tmp_path, path)
        except FileExistsError:
            raise
        except OSError:
            _publish_exclusive_via_creat(path, tmp_path)
            return
        tmp_path.unlink(missing_ok=True)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _publish_exclusive_via_creat(path: Path, tmp_path: Path) -> None:
    """Windows / non-link fallback: O_EXCL placeholder, then replace with tmp."""
    excl_fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(excl_fd)
    os.replace(tmp_path, path)


def _atomic_write(path: Path, content: str) -> None:
    # Follow symlinks so the link inode stays and the target is updated.
    target = path.resolve() if path.is_symlink() else path
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    prior_mode = target.stat().st_mode if target.is_file() else None
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=directory)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        if prior_mode is not None:
            os.chmod(tmp_path, prior_mode)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _upsert_managed_block(source: str) -> str:
    cleaned = _LEGACY_DOFILE_RE.sub("", source)
    cleaned = _strip_managed_regions(cleaned)
    return _insert_managed_block(cleaned)


def _strip_managed_regions(source: str) -> str:
    stripped = _MANAGED_BLOCK_RE.sub("", source)
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
            if stop < len(source) and source[stop] == "\r":
                stop += 1
            if stop < len(source) and source[stop] == "\n":
                stop += 1
            region = source[start:stop]
            # Refuse to delete a top-level return trapped between markers.
            if _top_level_return_in(region):
                source = _drop_line_at(source, orphan)
                continue
            source = source[:start] + source[stop:]
            continue
        return_match = _RETURN_LINE_RE.search(source, orphan.end())
        if return_match is not None:
            source = source[:start] + source[return_match.start() :]
            continue
        # No END and no return: strip only the orphan BEGIN line.
        source = _drop_line_at(source, orphan)
        continue


def _top_level_return_in(region: str) -> bool:
    return any(not match.group(1) for match in _RETURN_LINE_RE.finditer(region))


def _drop_line_at(source: str, match: re.Match[str]) -> str:
    stop = match.end()
    if stop < len(source) and source[stop] == "\r":
        stop += 1
    if stop < len(source) and source[stop] == "\n":
        stop += 1
    return source[: match.start()] + source[stop:]


def _long_comment_ranges(source: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = source.find(_LONG_COMMENT_OPEN, cursor)
        if start < 0:
            return ranges
        end = source.find(_LONG_COMMENT_CLOSE, start + len(_LONG_COMMENT_OPEN))
        if end < 0:
            ranges.append((start, len(source)))
            return ranges
        ranges.append((start, end + len(_LONG_COMMENT_CLOSE)))
        cursor = end + len(_LONG_COMMENT_CLOSE)


def _in_long_comment(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in ranges)


def _find_config_builder(source: str) -> re.Match[str] | None:
    comments = _long_comment_ranges(source)
    for match in _CONFIG_BUILDER_RE.finditer(source):
        if not _in_long_comment(match.start(), comments):
            return match
    return None


def _line_end_after(source: str, match: re.Match[str]) -> int:
    """Index just past the matched line's trailing newline (if any)."""
    stop = match.end()
    if stop < len(source) and source[stop] == "\r":
        stop += 1
    if stop < len(source) and source[stop] == "\n":
        stop += 1
    return stop


def _insert_managed_block(source: str) -> str:
    builder = _find_config_builder(source)
    if builder is not None:
        rest = source[builder.end() :].lstrip("\n")
        return f"{source[: builder.end()]}\n{_MANAGED_BLOCK}\n{rest}"

    require = _REQUIRE_WEZTERM_RE.search(source)
    if require is not None:
        line_end = _line_end_after(source, require)
        rest = source[line_end:].lstrip("\n")
        return f"{source[:line_end]}{_MANAGED_BLOCK}\n{rest}"

    # No builder / require: start of file so we precede any wezterm.on handlers.
    if source.strip():
        return f"{_MANAGED_BLOCK}\n{source.lstrip('\n')}"

    returns = list(_RETURN_LINE_RE.finditer(source))
    top_level = [match for match in returns if not match.group(1)]
    if top_level:
        match = top_level[-1]
        prefix = source[: match.start()].rstrip("\n")
        return f"{prefix}\n{_MANAGED_BLOCK}\n{source[match.start() :]}"

    separator = "" if source.endswith("\n") or source == "" else "\n"
    return f"{source}{separator}\n{_MANAGED_BLOCK}"
