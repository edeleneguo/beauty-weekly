import json
from pathlib import Path

from build.archive_current_issue import archive_current_issue


def _site(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "issues.json").write_text("[]\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("makeup august data", encoding="utf-8")
    (tmp_path / "fragrance.html").write_text("fragrance august data", encoding="utf-8")
    (tmp_path / "deploy-manifest.json").write_text(
        json.dumps({"month": "2026-08"}) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_archives_current_pages_and_registers_user_facing_issue_month(tmp_path):
    root = _site(tmp_path)

    archived = archive_current_issue(root, next_month="2026-09")

    assert archived is True
    archive = root / "archive" / "months" / "2026-08"
    assert (archive / "index.html").read_text() == "makeup august data"
    assert (archive / "fragrance.html").read_text() == "fragrance august data"
    issues = json.loads((root / "data" / "issues.json").read_text())
    assert issues[0] == {
        "id": "month-2026-08",
        "label": "September 2026",
        "sort_key": "2026-09-01",
        "language": "en",
        "makeup": "archive/months/2026-08/index.html",
        "fragrance": "archive/months/2026-08/fragrance.html",
    }


def test_archive_is_idempotent_for_same_published_month(tmp_path):
    root = _site(tmp_path)

    assert archive_current_issue(root, next_month="2026-09") is True
    assert archive_current_issue(root, next_month="2026-09") is False
    issues = json.loads((root / "data" / "issues.json").read_text())
    assert [issue["id"] for issue in issues] == ["month-2026-08"]


def test_does_not_archive_when_root_already_matches_target_month(tmp_path):
    root = _site(tmp_path)
    (root / "deploy-manifest.json").write_text(
        json.dumps({"month": "2026-09"}) + "\n", encoding="utf-8"
    )

    assert archive_current_issue(root, next_month="2026-09") is False
    assert not (root / "archive").exists()


def test_monthly_update_archives_in_stage_before_render_and_promotes_registry():
    script = (Path(__file__).parents[1] / "build" / "monthly_update.sh").read_text()

    assert script.index("build/archive_current_issue.py") < script.index("build/render.py")
    assert 'cp "$STAGE_DIR/data/issues.json" "data/issues.json"' in script
    assert 'archive/months' in script
