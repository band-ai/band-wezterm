"""Test bootstrap.

Loads repo-root ``.env.test`` (gitignored) the same way band-sdk-python and
band-plugin-vsc do — credentials for opt-in live tests.

The package is normally installed from pyproject.toml (`uv sync`). Fall back to
the in-repo source tree so a bare checkout can run `pytest` without an install.
"""

from __future__ import annotations

import sys
from importlib.util import find_spec

from dotenv import load_dotenv

from tests.live_settings import force_live_api_hosts
from tests.paths import ENV_TEST_FILE, REPO_ROOT

load_dotenv(ENV_TEST_FILE, override=False)
force_live_api_hosts()

SRC_DIR = REPO_ROOT / "src"

if find_spec("band_wezterm") is None:
    sys.path.insert(0, str(SRC_DIR))
