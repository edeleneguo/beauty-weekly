#!/usr/bin/env python3
"""Validate source evidence and new-product qualification integrity (Phase 7).

Fail-closed: exit 1 if any validation error is found.
Called from build/check.sh.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.evidence import validate_evidence_integrity  # noqa: E402
from beauty_weekly.month import month_data_dir, resolve_month  # noqa: E402
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402

MONTH = os.environ.get("BEAUTY_MONTHLY_MONTH")
TARGET_LABEL = resolve_month() if MONTH else resolve_week()
TARGET_DIR = month_data_dir(TARGET_LABEL) if MONTH else weeks_dir(TARGET_LABEL)


def main() -> int:
    print(f"Evidence & qualification integrity ({TARGET_LABEL}) ... ", end="")

    report_path = TARGET_DIR / "report.json"
    sources_path = TARGET_DIR / "sources.json"

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

    errors = validate_evidence_integrity(report, sources, is_historical=not bool(MONTH))

    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
