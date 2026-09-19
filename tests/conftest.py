"""Test bootstrap.

Loads repo-root ``.env.test`` (gitignored) the same way band-sdk-python and
band-plugin-vsc do — credentials for opt-in live tests, absent in CI.

The package is normally installed from pyproject.toml (`uv sync`). Fall back to
the in-repo source tree so a bare checkout can run `pytest` without an install.
"""

from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

from dotenv import load_dotenv

from tests.paths import ENV_TEST_FILE

load_dotenv(ENV_TEST_FILE, override=False)

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

if find_spec("band_wezterm") is None:
    sys.path.insert(0, str(SRC_DIR))
