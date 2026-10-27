import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_monthly_templates_keep_past_issues_selector():
    for page in ("index.html", "fragrance.html"):
        html = (ROOT / "templates" / "pages" / page).read_text(encoding="utf-8")
        assert 'class="issue-select"' in html
        assert 'aria-label="Current and past issues selector"' in html


def test_published_past_issue_links_resolve_to_restored_archives():
    for page in ("index.html", "fragrance.html"):
        html = (ROOT / page).read_text(encoding="utf-8")
        links = re.findall(r'<option value="(archive/[^"]+)">', html)
        assert links, f"{page} has no past-issue links"
        for link in links:
            assert (ROOT / link).is_file(), f"broken past-issue link in {page}: {link}"


def test_every_monthly_archive_can_return_to_current_issue():
    for page in (ROOT / "archive" / "months").rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        category = "fragrance.html" if page.name == "fragrance.html" else "index.html"
        assert f'value="../../../{category}"' in html
        assert "Current Issue · October 2026" in html
        selected = re.search(r'<option[^>]+selected>([^<]+)</option>', html)
        assert selected is not None
        assert selected.group(1) != "Current Issue · October 2026"
