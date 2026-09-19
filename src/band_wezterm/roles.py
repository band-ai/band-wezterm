"""Role library — plain Markdown personas under ``~/.band/roles`` (VSC parity)."""

from __future__ import annotations

import re
import shutil
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ROLES_DIRNAME = Path.home() / ".band" / "roles"
GENERATED_ROLES_DIRECTORY = ".generated"
DEFAULT_ROLES_PACKAGE = "band_wezterm.default_roles"

_FRONTMATTER = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?")
_FRONTMATTER_DESCRIPTION = re.compile(r"^description:\s*(.+)$", re.MULTILINE)
_ROLE_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_ROLE_HEADING_LINE = re.compile(r"^#\s+")


class Role(BaseModel):
    """One role file — ``id`` is the filename stem (stable across heading edits)."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    content: str
    description: str | None = None


def roles_directory(override: Path | str | None = None) -> Path:
    return Path(override) if override is not None else ROLES_DIRNAME


def role_file_stem(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def role_name_error(name: str, roles_dir: Path | str | None = None) -> str | None:
    stem = role_file_stem(name)
    if not stem:
        return "A role name needs at least one letter or digit."
    if (roles_directory(roles_dir) / f"{stem}.md").exists():
        return f'A role called "{stem}" already exists.'
    return None


def ensure_role_library(roles_dir: Path | str | None = None) -> Path:
    """Seed defaults once, then ensure the directory exists. Best-effort."""
    resolved = roles_directory(roles_dir)
    _seed_defaults_if_missing(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def create_role(name: str, roles_dir: Path | str | None = None) -> Path:
    resolved = ensure_role_library(roles_dir)
    trimmed = name.strip()
    path = resolved / f"{role_file_stem(trimmed)}.md"
    path.write_text(
        f"---\ndescription: \n---\n# {trimmed}\n\nYou are a {trimmed.lower()}.\n",
        encoding="utf-8",
    )
    return path


def list_roles(roles_dir: Path | str | None = None) -> list[Role]:
    resolved = ensure_role_library(roles_dir)
    roles: list[Role] = []
    for path in sorted(resolved.glob("*.md")):
        if path.name.startswith("."):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        roles.append(_parse_role(path.stem, content))
    return roles


def _seed_defaults_if_missing(roles_dir: Path) -> None:
    if roles_dir.exists():
        return
    try:
        roles_dir.mkdir(parents=True, exist_ok=True)
        package = resources.files(DEFAULT_ROLES_PACKAGE)
        for entry in package.iterdir():
            if entry.name.endswith(".md"):
                target = roles_dir / entry.name
                with resources.as_file(entry) as source:
                    shutil.copyfile(source, target)
    except OSError as error:
        # Role library is optional polish — a read-only home must not block register.
        print(f"Band: could not seed the default role library at {roles_dir}: {error}")


def _parse_role(stem: str, content: str) -> Role:
    frontmatter_match = _FRONTMATTER.match(content)
    frontmatter = frontmatter_match.group(1) if frontmatter_match else None
    body = content[frontmatter_match.end() :] if frontmatter_match else content
    description = _frontmatter_description(frontmatter) or _body_preview(body)
    heading = _ROLE_HEADING.search(body)
    label = heading.group(1).strip() if heading else stem
    return Role(id=stem, label=label, content=content, description=description)


def _frontmatter_description(frontmatter: str | None) -> str | None:
    if not frontmatter:
        return None
    match = _FRONTMATTER_DESCRIPTION.search(frontmatter)
    if match is None:
        return None
    raw = match.group(1).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1].strip()
    return raw or None


def _body_preview(content: str) -> str | None:
    lines = [line.strip() for line in content.splitlines()]
    first_body = next(
        (index for index, line in enumerate(lines) if line and not _ROLE_HEADING_LINE.match(line)),
        -1,
    )
    if first_body < 0:
        return None
    paragraph: list[str] = []
    for line in lines[first_body:]:
        if not line:
            break
        paragraph.append(line)
    preview = " ".join(paragraph).strip()
    return preview or None
