"""Test bootstrap.

The package is normally installed from pyproject.toml (`uv sync`), which is the
preferred path. Fall back to the in-repo source tree so a bare checkout can run
`pytest` without an install step.
"""

from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

if find_spec("band_wezterm") is None:
    sys.path.insert(0, str(SRC_DIR))
