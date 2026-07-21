#!/usr/bin/env python3
"""Validate canonical weekly dataset as part of the build quality gate.

Fail-closed: exit 1 if any validation error is found.
Called from build/check.sh.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.canonical import validate_canonical  # noqa: E402
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402

_weeks_dir_name = resolve_week()
WEEKS_DIR = weeks_dir(_weeks_dir_name)


def main() -> int:
    print(f"Canonical dataset validation ({_weeks_dir_name}) ... ", end="")
    errors = validate_canonical(WEEKS_DIR)

    if errors:
        print("FAIL")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
