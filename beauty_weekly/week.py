"""Dynamic ISO-week resolution for the weekly build pipeline.

Provides a single source of truth for which week the pipeline targets.
All build/validation/render scripts resolve the target week through this
module rather than hard-coding an ISO-week string.

Resolution order:
  1. ``BEAUTY_WEEKLY_WEEK`` environment variable (explicit override)
  2. ``TARGET_WEEK`` CLI argument (if the caller passes one)
  3. The most recent ``data/weeks/<iso-week>/`` directory that contains
     a valid ``report.json`` — this is the "latest published week".
  4. Fall back to the current calendar ISO week (``datetime.date.today()``).

The module also provides helpers for:
  * ``weeks_dir(week)`` — canonical path to a week's data directory
  * ``report_path(week)`` — canonical path to a week's report.json
  * ``available_weeks()`` — list of all week directories that contain report.json
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA_WEEKS = _ROOT / "data" / "weeks"


def current_iso_week(d: date | None = None) -> str:
    """Return the ISO week string for *d* (default: today).

    >>> current_iso_week(date(2026, 7, 21))
    '2026-W30'
    """
    if d is None:
        d = date.today()
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def available_weeks() -> list[str]:
    """Return sorted list of ISO-week strings that have a valid report.json."""
    weeks: list[str] = []
    if not _DATA_WEEKS.exists():
        return weeks
    for entry in sorted(_DATA_WEEKS.iterdir()):
        if entry.is_dir() and (
            (entry / "report.json").exists() or (entry / "raw_collected.json").exists()
        ):
            weeks.append(entry.name)
    return weeks


def resolve_week(target: str | None = None) -> str:
    """Resolve the target ISO week.

    Resolution order:
      1. ``BEAUTY_WEEKLY_WEEK`` env var (highest priority)
      2. Explicit *target* argument
      3. Most recent available week from ``data/weeks/``
      4. Current calendar ISO week
    """
    # 0. If BEAUTY_WEEKLY_REQUIRE_CURRENT=1, always use current week
    if os.environ.get("BEAUTY_WEEKLY_REQUIRE_CURRENT") == "1":
        return current_iso_week()

    # 1. Environment variable override
    env_week = os.environ.get("BEAUTY_WEEKLY_WEEK")
    if env_week:
        return _validate_week(env_week)

    # 2. Explicit argument
    if target:
        return _validate_week(target)

    # 3. Most recent available week
    avail = available_weeks()
    if avail:
        return avail[-1]

    # 4. Current calendar week
    return current_iso_week()


def _validate_week(week: str) -> str:
    """Validate and normalise an ISO week string."""
    import re

    m = re.fullmatch(r"(\d{4})-W(\d{2})", week)
    if not m:
        raise ValueError(
            f"Invalid ISO week string '{week}'. Expected format: YYYY-WNN (e.g. 2026-W29)"
        )
    return week


def weeks_dir(week: str | None = None) -> Path:
    """Return the canonical data directory for the given week."""
    w = resolve_week(week)
    return _DATA_WEEKS / w


def report_path(week: str | None = None) -> Path:
    """Return the canonical report.json path for the given week."""
    return weeks_dir(week) / "report.json"


def root() -> Path:
    """Return the repository root."""
    return _ROOT
