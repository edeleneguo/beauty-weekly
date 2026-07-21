#!/usr/bin/env python3
"""Validate source evidence and new-product qualification integrity (Phase 7).

Fail-closed: exit 1 if any validation error is found.
Called from build/check.sh.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.evidence import validate_evidence_integrity  # noqa: E402
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402

_weeks_dir_name = resolve_week()
WEEKS_DIR = weeks_dir(_weeks_dir_name)


def main() -> int:
    print(f"Evidence & qualification integrity ({_weeks_dir_name}) ... ", end="")

    report_path = WEEKS_DIR / "report.json"
    sources_path = WEEKS_DIR / "sources.json"

    if not report_path.exists():
        print("FAIL")
        print("  ERROR: report.json not found")
        return 1
    if not sources_path.exists():
        print("FAIL")
        print("  ERROR: sources.json not found")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    sources = json.loads(sources_path.read_text(encoding="utf-8"))

    errors = validate_evidence_integrity(report, sources, is_historical=True)

    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
