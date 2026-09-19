"""Repository filesystem anchors for the test suite.

``REPO_ROOT`` is defined once here — not re-derived per file with
``Path(__file__).parents[N]`` arithmetic.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_TEST_FILE = REPO_ROOT / ".env.test"
