"""Private temporary-file creation shared by managed agent launchers."""

from __future__ import annotations

import tempfile
from pathlib import Path


def write_private_text(*, content: str, prefix: str, suffix: str) -> Path:
    """Write a launch payload that only its child process should consume."""
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=prefix,
        suffix=suffix,
        delete=False,
    ) as handle:
        path = Path(handle.name)
        path.chmod(0o600)
        handle.write(content)
    return path
