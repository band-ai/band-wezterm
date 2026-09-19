"""Open / create roles in the shared ~/.band/roles library (VSC parity)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from band_wezterm.roles import create_role, ensure_role_library, role_name_error


def open_role_library(roles_dir: Path | str | None = None) -> Path:
    """Seed if needed, then reveal the roles folder in the OS file browser."""
    resolved = ensure_role_library(roles_dir)
    _reveal_path(resolved)
    return resolved


def create_and_open_role(name: str, roles_dir: Path | str | None = None) -> Path:
    """Create a starter role Markdown file and open it for editing."""
    error = role_name_error(name, roles_dir)
    if error:
        raise ValueError(error)
    path = create_role(name, roles_dir)
    _open_file(path)
    return path


def _reveal_path(path: Path) -> None:
    match sys.platform:
        case "darwin":
            subprocess.run(["open", str(path)], check=False)
        case "win32":
            subprocess.run(["explorer", str(path)], check=False)
        case _:
            opener = shutil.which("xdg-open")
            if opener:
                subprocess.run([opener, str(path)], check=False)


def _open_file(path: Path) -> None:
    match sys.platform:
        case "darwin":
            subprocess.run(["open", "-t", str(path)], check=False)
        case "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        case _:
            opener = shutil.which("xdg-open")
            if opener:
                subprocess.run([opener, str(path)], check=False)
