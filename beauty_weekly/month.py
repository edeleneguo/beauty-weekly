"""Dynamic month resolution for the monthly build pipeline.

Provides a single source of truth for which month the pipeline targets.
All build/validation/render scripts resolve the target month through this
module rather than hard-coding a month string.

The pipeline always reports on the **previous** calendar month relative to
the current date (or the date of the CI run).  A GitHub Actions cron on
day 1 at 01:00 UTC (09:00 Asia/Shanghai) triggers the run, which
processes the entirety of the prior calendar month.

Resolution order:
  1. ``BEAUTY_MONTHLY_MONTH`` environment variable (explicit override, YYYY-MM)
  2. ``TARGET_MONTH`` CLI argument (if the caller passes one, YYYY-MM)
  3. The most recent ``data/months/<YYYY-MM>/`` directory that contains
     a valid ``report.json``
  4. Fall back to the previous calendar month from today.

Module also provides:
  * ``previous_month_range(year, month)`` -- (start, end) as date objects
  * ``month_date_range_strs(year, month)`` -- (EN, CN) display strings
  * ``month_data_dir(month_str)`` -- canonical data path
  * ``month_archive_dir(month_str)`` -- archive output path
"""

from __future__ import annotations

import calendar
import os
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DATA_MONTHS = _ROOT / "data" / "months"


def previous_month(d: date | None = None) -> tuple[int, int]:
    """Return (year, month) of the calendar month prior to *d* (default: today).

    >>> previous_month(date(2026, 7, 1))
    (2026, 6)
    >>> previous_month(date(2026, 1, 1))
    (2025, 12)
    """
    if d is None:
        d = date.today()
    if d.month == 1:
        return d.year - 1, 12
    return d.year, d.month - 1


def month_str(year: int, month: int) -> str:
    """Return ``YYYY-MM`` string for a given year/month.

    >>> month_str(2026, 6)
    '2026-06'
    """
    return f"{year}-{month:02d}"


def previous_month_str(d: date | None = None) -> str:
    """Return ``YYYY-MM`` string for the previous calendar month.

    >>> previous_month_str(date(2026, 7, 15))
    '2026-06'
    """
    y, m = previous_month(d)
    return month_str(y, m)


def previous_month_range(year: int, month: int) -> tuple[date, date]:
    """Return (first_day, last_day) of the given calendar month.

    >>> previous_month_range(2026, 6)
    (datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    >>> previous_month_range(2026, 2)
    (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28))
    """
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def month_date_range_strs(year: int, month: int) -> tuple[str, str]:
    """Return (EN_display, CN_display) for the given month's date range.

    >>> month_date_range_strs(2026, 6)
    ('Jun 1 – Jun 30, 2026', '6月1日 – 6月30日')
    """
    first, last = previous_month_range(year, month)
    en = f"{first.strftime('%b')} {first.day} \u2013 {last.strftime('%b')} {last.day}, {first.year}"
    cn = f"{first.month}\u6708{first.day}\u65e5 \u2013 {last.month}\u6708{last.day}\u65e5"
    return en, cn


def available_months() -> list[str]:
    """Return sorted list of YYYY-MM strings that have a valid report.json."""
    months: list[str] = []
    if not _DATA_MONTHS.exists():
        return months
    for entry in sorted(_DATA_MONTHS.iterdir()):
        if entry.is_dir() and (
            (entry / "report.json").exists() or (entry / "raw_collected.json").exists()
        ):
            months.append(entry.name)
    return months


def resolve_month(target: str | None = None) -> str:
    """Resolve the target month.

    Resolution order:
      1. ``BEAUTY_MONTHLY_MONTH`` env var (highest priority)
      2. Explicit *target* argument
      3. Most recent available month from ``data/months/``
      4. Previous calendar month
    """
    # Environment variable override
    env_month = os.environ.get("BEAUTY_MONTHLY_MONTH")
    if env_month:
        return _validate_month(env_month)

    # Explicit argument
    if target:
        return _validate_month(target)

    # Most recent available month
    avail = available_months()
    if avail:
        return avail[-1]

    # Previous calendar month
    return previous_month_str()


def _validate_month(m: str) -> str:
    """Validate and normalise a YYYY-MM month string."""
    import re

    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", m)
    if not match:
        raise ValueError(f"Invalid month string '{m}'. Expected format: YYYY-MM (e.g. 2026-06)")
    return m


def month_data_dir(month: str | None = None) -> Path:
    """Return the canonical data directory for the given month."""
    m = resolve_month(month)
    return _DATA_MONTHS / m


def month_report_path(month: str | None = None) -> Path:
    """Return the canonical report.json path for the given month."""
    return month_data_dir(month) / "report.json"


def month_archive_dir(month: str | None = None) -> Path:
    """Return the archive output path for the given month."""
    m = resolve_month(month)
    return _ROOT / "archive" / m


def root() -> Path:
    """Return the repository root."""
    return _ROOT
