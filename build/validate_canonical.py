#!/usr/bin/env python3
"""Validate canonical weekly dataset as part of the build quality gate.

Fail-closed: exit 1 if any validation error is found.
Called from build/check.sh.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.canonical import validate_canonical  # noqa: E402
from beauty_weekly.month import month_data_dir, resolve_month  # noqa: E402
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402

MONTH = os.environ.get("BEAUTY_MONTHLY_MONTH")
TARGET_LABEL = resolve_month() if MONTH else resolve_week()
TARGET_DIR = month_data_dir(TARGET_LABEL) if MONTH else weeks_dir(TARGET_LABEL)


def main() -> int:
    print(f"Canonical dataset validation ({TARGET_LABEL}) ... ", end="")
    errors = validate_canonical(TARGET_DIR)

    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
