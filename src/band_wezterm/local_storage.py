"""Crash-safe persistence for small local JSON documents."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

LOCAL_FILE_MODE: Final = 0o600


def atomic_write_text(path: Path, content: str) -> None:
    """Replace ``path`` only after durable content is ready."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, LOCAL_FILE_MODE)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
