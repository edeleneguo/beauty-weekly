import json

from build.rebuild_monthly_archives import build_monthly_issue_registry


def test_registry_is_rebuilt_from_canonical_months_and_drops_legacy_weeks(tmp_path):
    months = tmp_path / "data" / "months"
    for month in ("2026-06", "2026-07", "2026-08", "2026-09"):
        month_dir = months / month
        month_dir.mkdir(parents=True)
        (month_dir / "report.json").write_text("{}\n", encoding="utf-8")
    registry_path = tmp_path / "data" / "issues.json"
    registry_path.write_text(
        json.dumps([{"id": "2026-W30", "label": "Week 30"}]), encoding="utf-8"
    )

    issues = build_monthly_issue_registry(tmp_path, current_month="2026-09")

    assert [issue["id"] for issue in issues] == [
        "month-2026-08",
        "month-2026-07",
        "month-2026-06",
    ]
    assert [issue["label"] for issue in issues] == [
        "September 2026",
        "August 2026",
        "July 2026",
    ]
    assert all("week" not in issue["makeup"] for issue in issues)
