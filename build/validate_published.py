#!/usr/bin/env python3
"""Pre-publish validation CLI (Req 2, 5).

Runs all pre-publish checks before allowing publication.  Failure
preserves stable Pages by aborting before any promotion.

Usage:
  python3 build/validate_published.py [WEEK]
  # If WEEK is omitted, uses BEAUTY_WEEKLY_WEEK env or resolves dynamically.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.validate_published import validate_for_publish  # noqa: E402
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402


def main() -> int:
    week = resolve_week()
    week_dir = weeks_dir(week)
    print(f"Pre-publish validation ({week}) ... ", end="")
    errors = validate_for_publish(week_dir, is_historical=False)
    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
