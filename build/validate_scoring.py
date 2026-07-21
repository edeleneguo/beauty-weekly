#!/usr/bin/env python3
"""Validate scoring policy and scoring.json consistency.

Phase 6: ensures the scoring module is internally consistent and that
scoring.json files validate against the scoring module's own schema checks.

Called from build/check.sh.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.scoring import (  # noqa: E402
    COMPONENT_IDS,
    SCORING_COMPONENTS,
    TOTAL_WEIGHT,
    validate_recomputed_scoring,
    validate_scoring_json,
)
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402

_weeks_dir_name = resolve_week()
WEEKS_DIR = weeks_dir(_weeks_dir_name)


def main() -> int:
    print(f"Scoring policy validation ({_weeks_dir_name}) ... ", end="")
    errors: list[str] = []

    # 1. Validate scoring module internal consistency
    if abs(TOTAL_WEIGHT - 1.0) > 1e-9:
        errors.append(f"TOTAL_WEIGHT={TOTAL_WEIGHT} does not sum to 1.0")

    if len(SCORING_COMPONENTS) != 4:
        errors.append(f"Expected 4 scoring components, got {len(SCORING_COMPONENTS)}")

    if len(set(COMPONENT_IDS)) != len(COMPONENT_IDS):
        errors.append("Duplicate component IDs found")

    for c in SCORING_COMPONENTS:
        if c["weight"] <= 0 or c["weight"] > 1:
            errors.append(f"Component {c['id']} weight {c['weight']} out of (0, 1]")

    # 2. Validate scoring.json
    scoring_path = WEEKS_DIR / "scoring.json"
    if not scoring_path.exists():
        errors.append("scoring.json not found")
    else:
        scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
        json_errors = validate_scoring_json(scoring)
        errors.extend(json_errors)

        # 3. For recomputable records, cross-validate against report
        if scoring.get("recomputable") is True:
            report_path = WEEKS_DIR / "report.json"
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                recompute_errors = validate_recomputed_scoring(scoring, report)
                errors.extend(recompute_errors)

    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
