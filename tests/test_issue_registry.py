import json
from pathlib import Path

import pytest
from beauty_weekly.issues import load_issues, relative_issue_url, render_issue_options

ROOT = Path(__file__).resolve().parent.parent


def test_registry_is_strictly_ordered_and_public_entries_are_english():
    issues = load_issues(ROOT / "data" / "issues.json")

    assert [issue["id"] for issue in issues] == [
        "month-2026-08",
        "2026-W30",
        "2026-W29",
        "2026-W28",
        "2026-W27",
        "2026-W26",
        "2026-W25",
        "2026-W23",
    ]
    assert all(issue["language"] == "en" for issue in issues)


def test_registry_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "issues.json"
    issue = {
        "id": "2026-W30",
        "label": "Week 30",
        "sort_key": "2026-07-26",
        "language": "en",
        "makeup": "archive/week-30/index.html",
        "fragrance": "archive/week-30/fragrance.html",
    }
    path.write_text(json.dumps([issue, issue]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate issue id"):
        load_issues(path, root=ROOT)


def test_relative_issue_url_accounts_for_archive_depth():
    target = ROOT / "archive" / "week-29" / "index.html"

    assert relative_issue_url(ROOT / "index.html", target) == "archive/week-29/index.html"
    assert (
        relative_issue_url(ROOT / "archive" / "week-30" / "index.html", target)
        == "../week-29/index.html"
    )


def test_options_are_complete_ordered_and_never_link_chinese_pages():
    page = ROOT / "archive" / "week-30" / "fragrance.html"

    options = render_issue_options(page, "fragrance", ROOT / "data" / "issues.json")

    assert options.index("Week 30") < options.index("Week 29") < options.index("Week 23")
    assert '../week-29/fragrance.html' in options
    assert "-cn.html" not in options
