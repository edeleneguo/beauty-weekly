#!/usr/bin/env python3
"""Archive the currently published monthly pages before root promotion."""

from __future__ import annotations

import argparse
import calendar
import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _issue_metadata(data_month: str) -> tuple[str, str]:
    year, month = map(int, data_month.split("-"))
    issue_year = year + (1 if month == 12 else 0)
    issue_month = 1 if month == 12 else month + 1
    return f"{calendar.month_name[issue_month]} {issue_year}", date(
        issue_year, issue_month, 1
    ).isoformat()


def archive_current_issue(root: Path = ROOT, *, next_month: str) -> bool:
    root = Path(root)
    manifest_path = root / "deploy-manifest.json"
    if not manifest_path.is_file():
        return False
    current_month = str(
        json.loads(manifest_path.read_text(encoding="utf-8")).get("month", "")
    )
    if not current_month or current_month == next_month:
        return False

    issue_id = f"month-{current_month}"
    registry_path = root / "data" / "issues.json"
    issues = json.loads(registry_path.read_text(encoding="utf-8"))
    if any(issue.get("id") == issue_id for issue in issues):
        return False

    source_pages = {
        "makeup": root / "index.html",
        "fragrance": root / "fragrance.html",
    }
    missing = [str(path) for path in source_pages.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"cannot archive current issue; missing: {', '.join(missing)}")

    archive_dir = root / "archive" / "months" / current_month
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pages["makeup"], archive_dir / "index.html")
    shutil.copy2(source_pages["fragrance"], archive_dir / "fragrance.html")

    label, sort_key = _issue_metadata(current_month)
    issues.append(
        {
            "id": issue_id,
            "label": label,
            "sort_key": sort_key,
            "language": "en",
            "makeup": f"archive/months/{current_month}/index.html",
            "fragrance": f"archive/months/{current_month}/fragrance.html",
        }
    )
    issues.sort(key=lambda issue: issue.get("sort_key", ""), reverse=True)
    registry_path.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--next-month", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    archived = archive_current_issue(args.root.resolve(), next_month=args.next_month)
    print("archived current monthly issue" if archived else "monthly archive already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
