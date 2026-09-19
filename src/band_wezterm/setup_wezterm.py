"""Idempotent WezTerm config wiring for the Band plugin."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path
from typing import Final

from band_wezterm.config import LOCAL_STATE_DIRNAME
from band_wezterm.wezterm_cli import wezterm_bin

# Default public/clone URL — overridden by materialize or BAND_WEZTERM_PLUGIN_URL.
WEZTERM_PLUGIN_URL: Final = "https://github.com/band-ai/band-wezterm"
BAND_WEZTERM_PLUGIN_URL_ENV: Final = "BAND_WEZTERM_PLUGIN_URL"
MANAGED_BEGIN: Final = "-- BEGIN BAND-WEZTERM MANAGED"
MANAGED_END: Final = "-- END BAND-WEZTERM MANAGED"
HOME_CONFIG_NAME: Final = ".wezterm.lua"
DEFAULT_CONFIG_DIRNAME: Final = ".config"
XDG_WEZTERM_RELATIVE: Final = Path("wezterm") / "wezterm.lua"
WEZTERM_CONFIG_FILE_ENV: Final = "WEZTERM_CONFIG_FILE"
XDG_CONFIG_HOME_ENV: Final = "XDG_CONFIG_HOME"
LEGACY_PLUGIN_BASENAME: Final = "band.wezterm.lua"
PLUGIN_REPO_DIRNAME: Final = "wezterm-plugin"
PLUGIN_PACKAGE: Final = "band_wezterm.wezterm_plugin"
PLUGIN_INIT_NAME: Final = "init.lua"

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
    r"^[ \t]*(?:local[ \t]+)?config[ \t]*=[ \t]*wezterm\.config_builder\s*\(\s*\)[^\n]*\r?\n",
    re.MULTILINE,
)
_REQUIRE_WEZTERM_RE: Final = re.compile(
    r"^[ \t]*(?:local[ \t]+\w+[ \t]*=[ \t]*)?require\s*\(?\s*['\"]wezterm['\"].*$",
    re.MULTILINE,
)
_WEZTERM_ON_RE: Final = re.compile(r"wezterm\.on\b")
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
    # Sandbox XDG when callers pass an explicit home (tests); production reads env.
    if home is None and XDG_CONFIG_HOME_ENV in os.environ:
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

    plugin_url = resolve_plugin_require_url(home=home)
    path = resolve_wezterm_config_path(home=home)
    if path.is_symlink() and not path.exists():
        raise SetupConfigError(f"WezTerm config path is a broken symlink: {path}")
    if path.exists() and not path.is_file():
        raise SetupConfigError(f"WezTerm config path is not a file: {path}")
    if not path.is_file():
        return _create_fresh_config(path, plugin_url=plugin_url)
    return _write_upserted(path, plugin_url=plugin_url)


def resolve_plugin_require_url(*, home: Path | None = None) -> str:
    """URL passed to ``wezterm.plugin.require``.

    Prefer ``BAND_WEZTERM_PLUGIN_URL`` (file:// checkout or HTTPS). Otherwise
    materialize the packaged Lua into a local git repo and return its file://
    URL — WezTerm only accepts HTTPS/file git URLs, and private GitHub HTTPS
    clones fail without credentials in WezTerm's libgit2.
    """
    override = os.environ.get(BAND_WEZTERM_PLUGIN_URL_ENV, "").strip()
    if override:
        return override
    return materialize_plugin_repo(home=home).as_uri()


def materialize_plugin_repo(*, home: Path | None = None) -> Path:
    """Write packaged ``plugin/init.lua`` into a tiny git repo under local state."""
    home_dir = home if home is not None else Path.home()
    root = (home_dir / LOCAL_STATE_DIRNAME / PLUGIN_REPO_DIRNAME).resolve()
    plugin_dir = root / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target = plugin_dir / PLUGIN_INIT_NAME
    source_text = _plugin_init_lua_text()
    if not target.is_file() or target.read_text(encoding="utf-8") != source_text:
        target.write_text(source_text, encoding="utf-8")
        _git_commit_plugin_repo(root)
    elif not (root / ".git").is_dir():
        _git_commit_plugin_repo(root)
    return root


def _plugin_init_lua_text() -> str:
    packaged = resources.files(PLUGIN_PACKAGE).joinpath(PLUGIN_INIT_NAME)
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    # Editable checkout: repo-root plugin/init.lua (parents: band_wezterm → src → repo).
    repo_plugin = Path(__file__).resolve().parents[2] / "plugin" / PLUGIN_INIT_NAME
    if repo_plugin.is_file():
        return repo_plugin.read_text(encoding="utf-8")
    raise SetupConfigError(
        "Band WezTerm plugin Lua is missing from the install "
        f"(expected {PLUGIN_PACKAGE}/{PLUGIN_INIT_NAME} or repo plugin/{PLUGIN_INIT_NAME})"
    )


def _git_commit_plugin_repo(root: Path) -> None:
    def _git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

    if not (root / ".git").is_dir():
        _git("init")
    _git("add", f"plugin/{PLUGIN_INIT_NAME}")
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return
    _git(
        "-c",
        "user.name=band-wezterm",
        "-c",
        "user.email=band-wezterm@localhost",
        "commit",
        "-m",
        "band-wezterm WezTerm plugin",
    )


def _managed_block(plugin_url: str) -> str:
    return (
        f"{MANAGED_BEGIN}\n"
        "do\n"
        "  local wezterm = require 'wezterm'\n"
        f"  local band = wezterm.plugin.require '{plugin_url}'\n"
        "  band.apply_to_config(config)\n"
        "end\n"
        f"{MANAGED_END}\n"
    )


def _fresh_config(plugin_url: str) -> str:
    return (
        "local wezterm = require 'wezterm'\n"
        "local config = wezterm.config_builder()\n"
        "\n"
        f"{_managed_block(plugin_url)}\n"
        "return config\n"
    )


def _create_fresh_config(path: Path, *, plugin_url: str) -> SetupResult:
    try:
        _publish_exclusive(path, _fresh_config(plugin_url))
    except FileExistsError:
        return _write_upserted(path, plugin_url=plugin_url)
    return SetupResult(path=path, action=SetupAction.CREATED)


def _write_upserted(path: Path, *, plugin_url: str) -> SetupResult:
    current = path.read_text(encoding="utf-8")
    if not current.strip():
        _atomic_write(path, _fresh_config(plugin_url))
        return SetupResult(path=path, action=SetupAction.CREATED)

    updated = _upsert_managed_block(current, plugin_url=plugin_url)
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
            # Expected when link is unsupported (e.g. Windows, EXDEV, EPERM).
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


def _upsert_managed_block(source: str, *, plugin_url: str) -> str:
    cleaned = _LEGACY_DOFILE_RE.sub("", source)
    cleaned = _strip_orphan_begins(_MANAGED_BLOCK_RE.sub("", cleaned))
    if not cleaned.strip():
        return _fresh_config(plugin_url)
    return _insert_managed_block(cleaned, plugin_url=plugin_url)


def _consume_newline(source: str, index: int) -> int:
    """Advance past a single ``\\r``, ``\\n``, or ``\\r\\n`` at ``index``."""
    if index < len(source) and source[index] == "\r":
        index += 1
    if index < len(source) and source[index] == "\n":
        index += 1
    return index


def _strip_orphan_begins(source: str) -> str:
    while True:
        orphan = _ORPHAN_BEGIN_RE.search(source)
        if orphan is None:
            return source
        start = orphan.start()
        end_match = re.search(re.escape(MANAGED_END), source[orphan.end() :])
        if end_match is not None:
            stop = _consume_newline(source, orphan.end() + end_match.end())
            region = source[start:stop]
            # Refuse to delete a return trapped between markers.
            if _RETURN_LINE_RE.search(region) is not None:
                source = _drop_line_at(source, orphan)
                continue
            source = source[:start] + source[stop:]
            continue
        return_match = _RETURN_LINE_RE.search(source, orphan.end())
        if return_match is not None:
            source = source[:start] + source[return_match.start() :]
            continue
        source = _drop_line_at(source, orphan)
        continue


def _drop_line_at(source: str, match: re.Match[str]) -> str:
    return source[: match.start()] + source[_line_end_after(source, match) :]


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


def _first_match_outside_long_comments(
    source: str, pattern: re.Pattern[str]
) -> re.Match[str] | None:
    comments = _long_comment_ranges(source)
    for match in pattern.finditer(source):
        if not any(start <= match.start() < end for start, end in comments):
            return match
    return None


def _line_end_after(source: str, match: re.Match[str]) -> int:
    """Index just past the matched line's trailing newline (if any)."""
    return _consume_newline(source, match.end())


def _insert_managed_block(source: str, *, plugin_url: str) -> str:
    block = _managed_block(plugin_url)
    builder = _first_match_outside_long_comments(source, _CONFIG_BUILDER_RE)
    if builder is not None:
        rest = source[builder.end() :].lstrip("\n")
        return f"{source[: builder.end()]}\n{block}\n{rest}"

    require = _first_match_outside_long_comments(source, _REQUIRE_WEZTERM_RE)
    if require is not None:
        line_end = _line_end_after(source, require)
        rest = source[line_end:].lstrip("\n")
        return f"{source[:line_end]}{block}\n{rest}"

    returns = list(_RETURN_LINE_RE.finditer(source))
    top_level = [match for match in returns if not match.group(1)]
    if top_level:
        last_return = top_level[-1]
        on_match = _WEZTERM_ON_RE.search(source, 0, last_return.start())
        if on_match is not None:
            # Band must run before user wezterm.on handlers.
            return f"{block}\n{source.lstrip('\n')}"
        prefix = source[: last_return.start()].rstrip("\n")
        return f"{prefix}\n{block}\n{source[last_return.start() :]}"

    # _upsert_managed_block never passes blank source here.
    return f"{block}\n{source.lstrip('\n')}"
