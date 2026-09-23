"""Fail CI when the branch-coverage ratchet is not met."""

from __future__ import annotations

import json
import sys
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Final

PYPROJECT_PATH: Final = Path("pyproject.toml")
COVERAGE_TABLE: Final = ("tool", "band-wezterm", "coverage")
MINIMUM_BRANCH_COVERAGE_KEY: Final = "minimum_branch_coverage"
TOTALS_KEY: Final = "totals"
COVERED_BRANCHES_KEY: Final = "covered_branches"
BRANCHES_KEY: Final = "num_branches"
PERCENT: Final = Decimal("100")


def minimum_branch_coverage() -> Decimal:
    """Read the single configured branch-coverage ratchet."""
    config = tomllib.loads(PYPROJECT_PATH.read_text())
    table: object = config
    for key in COVERAGE_TABLE:
        if not isinstance(table, dict) or key not in table:
            raise ValueError(f"Missing [{'.'.join(COVERAGE_TABLE)}] configuration.")
        table = table[key]
    if not isinstance(table, dict) or MINIMUM_BRANCH_COVERAGE_KEY not in table:
        raise ValueError(f"Missing {MINIMUM_BRANCH_COVERAGE_KEY} configuration.")
    return Decimal(str(table[MINIMUM_BRANCH_COVERAGE_KEY]))


def branch_totals(report_path: Path) -> tuple[int, int]:
    """Return covered and total branch opportunities from a coverage JSON report."""
    report = json.loads(report_path.read_text())
    totals = report.get(TOTALS_KEY)
    if not isinstance(totals, dict):
        raise ValueError("Coverage report has no totals.")
    covered = totals.get(COVERED_BRANCHES_KEY)
    total = totals.get(BRANCHES_KEY)
    if not isinstance(covered, int) or not isinstance(total, int) or total <= 0:
        raise ValueError("Coverage report has no branch data.")
    return covered, total


def main() -> int:
    report_path = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("coverage.json")
    minimum = minimum_branch_coverage()
    covered, total = branch_totals(report_path)
    actual = Decimal(covered) * PERCENT / Decimal(total)
    print(f"Branch coverage: {actual:.2f}% ({covered}/{total}); required: {minimum:.2f}%")
    if actual < minimum:
        print("Branch coverage is below the configured ratchet.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
