#!/usr/bin/env python3
"""Rebuild historical monthly pages from canonical data and current templates."""

from __future__ import annotations

import argparse
import calendar
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _issue_metadata(data_month: str) -> tuple[str, str]:
    year, month = map(int, data_month.split("-"))
    issue_year = year + (month == 12)
    issue_month = 1 if month == 12 else month + 1
    issue_date = date(issue_year, issue_month, 1)
    return f"{calendar.month_name[issue_month]} {issue_year}", issue_date.isoformat()


def build_monthly_issue_registry(root: Path, *, current_month: str) -> list[dict]:
    root = Path(root)
    months_root = root / "data" / "months"
    months = sorted(
        (
            path.name
            for path in months_root.iterdir()
            if path.is_dir()
            and path.name < current_month
            and (path / "report.json").is_file()
        ),
        reverse=True,
    )
    issues = []
    for month in months:
        label, sort_key = _issue_metadata(month)
        issues.append(
            {
                "id": f"month-{month}",
                "label": label,
                "sort_key": sort_key,
                "language": "en",
                "makeup": f"archive/months/{month}/index.html",
                "fragrance": f"archive/months/{month}/fragrance.html",
            }
        )
    registry_path = root / "data" / "issues.json"
    registry_path.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return issues


def rebuild_monthly_archives(root: Path, *, current_month: str) -> list[dict]:
    root = Path(root)
    issues = build_monthly_issue_registry(root, current_month=current_month)
    archive_root = root / "archive" / "months"
    if archive_root.exists():
        shutil.rmtree(archive_root)
    archive_root.mkdir(parents=True)

    for issue in issues:
        month = issue["id"].removeprefix("month-")
        output_dir = archive_root / month
        env = os.environ.copy()
        env.update(
            {
                "BEAUTY_MONTHLY_MONTH": month,
                "BEAUTY_WEEKLY_OUTPUT_DIR": str(output_dir),
                "BEAUTY_USE_CURRENT_TEMPLATE": "1",
            }
        )
        subprocess.run(
            [sys.executable, str(root / "build" / "render.py")],
            cwd=root,
            env=env,
            check=True,
        )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-month", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    issues = rebuild_monthly_archives(
        args.root.resolve(), current_month=args.current_month
    )
    print(f"rebuilt {len(issues)} historical monthly issue(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
