#!/usr/bin/env python3
"""Validate monthly target month (BEAUTY_MONTHLY_MONTH / resolve_month), not weekly path.

This script validates the monthly report.json using the target month from
environment variables, not the weekly path from validate_published.py.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import month_report_path  # noqa: E402
from beauty_weekly.validate_published import validate_for_publish  # noqa: E402


def main() -> int:
    # Get monthly report path directly
    report_path = Path(month_report_path())
    if not report_path.exists():
        print(f"ERROR: Monthly report not found: {report_path}")
        return 1

    # Extract month from path and validate
    month = report_path.parent.name
    month_dir = report_path.parent
    print(f"Pre-publish validation for month ({month}) ... ", end="")
    errors = validate_for_publish(month_dir, is_historical=False)
    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
