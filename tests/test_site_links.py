from pathlib import Path

from build.check_site_links import collect_broken_links

ROOT = Path(__file__).resolve().parent.parent


def test_collect_broken_links_resolves_links_relative_to_each_page(tmp_path):
    archive = tmp_path / "archive" / "week-30"
    archive.mkdir(parents=True)
    (tmp_path / "index.html").write_text("<p>current</p>", encoding="utf-8")
    page = archive / "index.html"
    page.write_text(
        '<a href="../../index.html">Current</a>'
        '<select><option value="../week-29/index.html">Week 29</option></select>',
        encoding="utf-8",
    )

    broken = collect_broken_links(tmp_path, pages=[page])

    assert broken == [(page, "../week-29/index.html")]


def test_repository_has_no_broken_public_html_links():
    broken = collect_broken_links(ROOT)

    assert broken == []
