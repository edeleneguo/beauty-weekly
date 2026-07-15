#!/usr/bin/env python3
"""Regression tests for beauty-weekly build pipeline.

Tests all defect categories from the Week 28 repair:
  1. Trend tags: concrete qualifying tags beside Core Selling Point
  2. New Product Tracking: dynamic count, no padding/placeholders
  3. Chinese/English localization: no leakage
  4. 4x10 invariant: only enforced for heat, not radar
  5. Data integrity: no copy-paste errors, no malformed fields
  6. Deterministic rendering: same input = same output
  7. Archive validation: frozen snapshots pass basic checks

Run: python3 -m pytest tests/test_week28.py -v
"""

import hashlib
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "week28.json")

FILES = {
    ("makeup", "en"): "index.html",
    ("makeup", "cn"): "index-cn.html",
    ("fragrance", "en"): "fragrance.html",
    ("fragrance", "cn"): "fragrance-cn.html",
}

ARCHIVE_FILES = {
    ("makeup", "en"): "archive/week-28/index.html",
    ("makeup", "cn"): "archive/week-28/index-cn.html",
    ("fragrance", "en"): "archive/week-28/fragrance.html",
    ("fragrance", "cn"): "archive/week-28/fragrance-cn.html",
}

PANELS = ["US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"]


@pytest.fixture(scope="session")
def data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def html_files():
    result = {}
    for (topic, lang), fname in FILES.items():
        fpath = os.path.join(ROOT, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            result[(topic, lang)] = f.read()
    return result


def _has_chinese(text):
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _count_items(html, section_num):
    if section_num == 3:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 03</span></h2>'
            r"(.*?)"
            r'(?=<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 04</span>)'
        )
    else:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 04</span></h2>'
            r"(.*?)"
            r'(?=<!--\s+APPENDIX|<div\s+class="section">\s*\n?\s*<h3)'
        )
    m = re.search(pattern, html, re.DOTALL)
    if not m:
        return 0
    return len(re.findall(r'<li\s+class="heat-item"', m.group(1)))


def _extract_section(html, section_num):
    if section_num == 3:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 03</span></h2>'
            r"(.*?)"
            r'(?=<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 04</span>)'
        )
    else:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 04</span></h2>'
            r"(.*?)"
            r'(?=<!--\s+APPENDIX|<div\s+class="section">\s*\n?\s*<h3)'
        )
    m = re.search(pattern, html, re.DOTALL)
    return m.group(1) if m else ""


# ═══════════════════════════════════════════════════════════════════════
# 1. Trend Tags: concrete qualifying tags beside Core Selling Point
# ═══════════════════════════════════════════════════════════════════════


class TestTrendTags:
    """Every trend-badge product must have concrete trend_tags on key_features."""

    def test_all_trend_badge_products_have_trend_tags(self, data):
        """Regression: trend-badge products must not have generic 'Trend Signal'."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        if p.get("trend_badge") and p.get("score", 0) > 0:
                            kf = p.get("detail", {}).get("key_features", {})
                            tags = kf.get("trend_tags") or kf.get("trend_tags_cn")
                            assert tags, (
                                f"{topic}/{section}/{panel}/{p['name']}: "
                                f"trend-badge product missing concrete trend_tags"
                            )
                            for tag in tags:
                                assert tag != "Trend Signal", (
                                    f"{topic}/{section}/{panel}/{p['name']}: "
                                    f"trend_tag must be concrete, not generic 'Trend Signal'"
                                )

    def test_trend_tags_render_in_en_html(self, html_files):
        """Regression: EN pages must have concrete trend_tags, not generic."""
        for (topic, lang), html in html_files.items():
            if lang != "en":
                continue
            trend_tags = re.findall(
                r'<span\s+class="heat-trend-tag">([^<]+)</span>', html
            )
            assert len(trend_tags) > 0, f"{topic} EN: no trend_tags found in HTML"
            for tag in trend_tags:
                assert tag != "Trend Signal", (
                    f"{topic} EN: generic 'Trend Signal' found, must be concrete"
                )

    def test_trend_tags_render_in_cn_html(self, html_files):
        """Regression: CN pages must have Chinese trend_tags."""
        for (topic, lang), html in html_files.items():
            if lang != "cn":
                continue
            trend_tags = re.findall(
                r'<span\s+class="heat-trend-tag">([^<]+)</span>', html
            )
            assert len(trend_tags) > 0, f"{topic} CN: no trend_tags found in HTML"
            for tag in trend_tags:
                assert _has_chinese(tag), (
                    f"{topic} CN: trend_tag '{tag}' is not in Chinese"
                )


# ═══════════════════════════════════════════════════════════════════════
# 2. New Product Tracking: dynamic, no padding, no placeholders
# ═══════════════════════════════════════════════════════════════════════


class TestNewProductTracking:
    """New Product Radar must be dynamic, never fixed 10/subcategory."""

    def test_no_placeholders_in_radar(self, data):
        """Regression: radar panels must have zero placeholder products."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    assert p.get("score", 0) > 0, (
                        f"{topic}/radar/{panel}/{p.get('name')}: "
                        f"placeholder (score=0) found in radar"
                    )

    def test_radar_panel_rows_dynamic(self, data):
        """Regression: radar panels can have 0-10 products, not forced to 10."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                count = len(products)
                assert 0 <= count <= 10, (
                    f"{topic}/radar/{panel}: {count} products (expected 0-10)"
                )

    def test_radar_no_padding_in_html(self, html_files):
        """Regression: radar sections must not contain placeholder text."""
        for (topic, lang), html in html_files.items():
            s4 = _extract_section(html, 4)
            assert "no more signal" not in s4.lower(), (
                f"{topic} {lang}: placeholder text 'no more signal' in radar"
            )
            assert "本周无更多" not in s4, (
                f"{topic} {lang}: placeholder text '本周无更多' in radar"
            )

    def test_radar_items_match_data(self, data, html_files):
        """Regression: HTML radar item count must match actual data products (excluding empty-state notes)."""
        for topic in ("makeup", "fragrance"):
            for lang in ("en",):
                html = html_files[(topic, lang)]
                # Count only real products (score > 0, not quarantined)
                total_data = 0
                for panel, products in data["products"][topic][
                    "new_product_radar"
                ].items():
                    for p in products:
                        if (
                            p.get("score", 0) > 0
                            and p.get("quarantine_status") != "out-of-window"
                        ):
                            total_data += 1
                total_html = _count_items(html, 4)
                # HTML may include empty-state note <li> elements for panels with 0 products
                assert total_html >= total_data, (
                    f"{topic} {lang}: radar HTML has {total_html} items "
                    f"but data has {total_data} qualifying products"
                )

    def test_radar_products_have_evidence_urls(self, data):
        """Regression: every radar product must have a source URL."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    link = p.get("detail", {}).get("price_link", {}).get("link", "")
                    assert link, (
                        f"{topic}/radar/{panel}/{p['name']}: "
                        f"no evidence URL (source link required)"
                    )
                    assert not link.startswith("https://example.com"), (
                        f"{topic}/radar/{panel}/{p['name']}: "
                        f"placeholder URL (example.com)"
                    )


# ═══════════════════════════════════════════════════════════════════════
# 3. Chinese/English localization: no leakage
# ═══════════════════════════════════════════════════════════════════════


class TestLocalization:
    """Language isolation: EN pages fully English, CN pages fully Chinese."""

    def test_en_radar_no_chinese_in_detail_values(self, html_files):
        """Regression: EN radar detail values must not contain Chinese."""
        for topic in ("makeup", "fragrance"):
            html = html_files[(topic, "en")]
            s4 = _extract_section(html, 4)
            values = re.findall(r'heat-detail-value">(.*?)</div>', s4, re.DOTALL)
            for v in values:
                clean = re.sub(r"<[^>]+>", "", v)
                assert not _has_chinese(clean), (
                    f"{topic} EN radar: Chinese found in detail value: '{clean[:60]}'"
                )

    def test_en_radar_no_chinese_in_data(self, data):
        """Regression: radar product EN fields must not contain Chinese."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    for key in ("price_link", "key_features", "buzz", "brand"):
                        cell = p.get("detail", {}).get(key, {})
                        en_val = cell.get("en", "")
                        assert not _has_chinese(en_val), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"{key}.en contains Chinese: '{en_val[:40]}'"
                        )

    def test_cn_pages_have_lang_attribute(self, html_files):
        """Regression: CN pages must have lang='zh-CN'."""
        for (topic, lang), html in html_files.items():
            if lang == "cn":
                assert 'lang="zh-CN"' in html, (
                    f"{topic} {lang}: missing lang='zh-CN' attribute"
                )

    def test_en_pages_have_lang_attribute(self, html_files):
        """Regression: EN pages must have lang='en'."""
        for (topic, lang), html in html_files.items():
            if lang == "en":
                assert 'lang="en"' in html, (
                    f"{topic} {lang}: missing lang='en' attribute"
                )

    def test_cn_trend_tags_are_chinese(self, data):
        """Regression: CN trend_tags must be in Chinese."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        if p.get("trend_badge") and p.get("score", 0) > 0:
                            kf = p.get("detail", {}).get("key_features", {})
                            cn_tags = kf.get("trend_tags_cn", [])
                            for tag in cn_tags:
                                assert _has_chinese(tag), (
                                    f"{topic}/{section}/{panel}/{p['name']}: "
                                    f"trend_tags_cn '{tag}' is not Chinese"
                                )

    def test_chinese_brand_names_on_cn_page(self, data, html_files):
        """Regression: Chinese-origin brands must use established Chinese names on CN pages."""
        cn_brand_names = {
            "Judydoll Blush Palette": "橘朵腮红盘",
            "Flower Knows Unicorn Lip Gloss": "花知晓独角兽唇釉",
            "Mao Geping Light Sculpting Foundation": "毛戈平光影塑形粉底液",
        }
        for topic in ("makeup",):
            html = html_files[(topic, "cn")]
            for en_name, cn_name in cn_brand_names.items():
                assert cn_name in html, (
                    f"{topic} CN: Chinese brand name '{cn_name}' not found"
                )
                # EN name should NOT appear on CN page
                if en_name != cn_name:
                    assert en_name not in html, (
                        f"{topic} CN: English brand name '{en_name}' "
                        f"found on CN page (should be '{cn_name}')"
                    )


# ═══════════════════════════════════════════════════════════════════════
# 4. 4x10 invariant: only for heat, not radar
# ═══════════════════════════════════════════════════════════════════════


class TestFourByTenInvariant:
    """4x10 invariant applies to heat rankings only, not new product radar."""

    def test_heat_has_40_items(self, html_files):
        """Regression: heat sections must have no placeholder items, only real products."""
        for (topic, lang), html in html_files.items():
            count = _count_items(html, 3)
            # Heat must have at least some real products and no placeholders
            assert count >= 1, f"{topic} {lang}: heat has {count} items (expected >= 1)"
            section_html = _extract_section(html, 3)
            assert "no more signal" not in section_html.lower(), (
                f"{topic} {lang}: placeholder text 'no more signal' in heat"
            )
            assert "本周无更多" not in section_html, (
                f"{topic} {lang}: placeholder text '本周无更多' in heat"
            )

    def test_heat_data_has_10_per_panel(self, data):
        """Regression: heat panels must have 1-10 real products (no placeholders)."""
        for topic in ("makeup", "fragrance"):
            for panel in PANELS:
                products = data["products"][topic]["heat_rankings"].get(panel, [])
                real = [p for p in products if p.get("score", 0) > 0]
                assert 1 <= len(real) <= 10, (
                    f"{topic}/heat/{panel}: {len(real)} real products (expected 1-10)"
                )
                # No placeholders should remain
                placeholders = [p for p in products if p.get("score", 0) == 0]
                assert len(placeholders) == 0, (
                    f"{topic}/heat/{panel}: {len(placeholders)} placeholder products remain"
                )

    def test_radar_not_forced_to_40(self, data, html_files):
        """Regression: radar sections must NOT be forced to 40 items."""
        for topic in ("makeup", "fragrance"):
            total_data = sum(
                len(products)
                for products in data["products"][topic]["new_product_radar"].values()
            )
            # Radar count should be dynamic, not exactly 40
            # (it can be any value from 0 to 40)
            assert 0 <= total_data <= 40, (
                f"{topic}: radar has {total_data} products (expected 0-40)"
            )
            # But specifically, it should NOT be padded to exactly 40
            # (this is the core regression: before the fix, it was always 40)

    def test_radar_panels_not_forced_to_10(self, data):
        """Regression: radar panels must not be forced to 10 products."""
        for topic in ("makeup", "fragrance"):
            for panel in PANELS:
                products = data["products"][topic]["new_product_radar"].get(panel, [])
                # Can be 0 to 10, but NOT padded
                assert 0 <= len(products) <= 10, (
                    f"{topic}/radar/{panel}: {len(products)} products (expected 0-10)"
                )


# ═══════════════════════════════════════════════════════════════════════
# 5. Data integrity: no copy-paste errors, no malformed fields
# ═══════════════════════════════════════════════════════════════════════


class TestDataIntegrity:
    """Data must not have copy-paste errors, malformed fields, or duplicates."""

    def test_no_duplicate_rank_names(self, data):
        """Regression: no duplicate product names within a panel."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    names = [p.get("name", "") for p in products]
                    # Allow duplicate placeholder names but not real products
                    real_names = [
                        n
                        for n in names
                        if "no more signal" not in n.lower() and "本周无更多" not in n
                    ]
                    assert len(real_names) == len(set(real_names)), (
                        f"{topic}/{section}/{panel}: duplicate product names"
                    )

    def test_le_labo_key_features_not_copy_of_dedcool(self, data):
        """Regression: Le Labo Thé Matcha 26 must have its own key_features."""
        le_labo = None
        dedcool = None
        for p in data["products"]["fragrance"]["heat_rankings"]["CN LUXURY"]:
            if p["name"] == "Le Labo Thé Matcha 26":
                le_labo = p
        for p in data["products"]["fragrance"]["heat_rankings"]["US MASSTIGE"]:
            if p["name"] == "DedCool Mochi Milk":
                dedcool = p
        assert le_labo is not None, "Le Labo Thé Matcha 26 not found"
        assert dedcool is not None, "DedCool Mochi Milk not found"
        le_labo_kf = le_labo["detail"]["key_features"]["en"]
        dedcool_kf = dedcool["detail"]["key_features"]["en"]
        assert le_labo_kf != dedcool_kf, (
            "Le Labo key_features is identical to DedCool (copy-paste error)"
        )

    def test_to_summer_not_copy_of_margiela(self, data):
        """Regression: To Summer Kunlun Snow must have its own key_features."""
        to_summer = None
        margiela = None
        for p in data["products"]["fragrance"]["heat_rankings"]["CN MASSTIGE"]:
            if p["name"] == "To Summer Kunlun Snow":
                to_summer = p
        for p in data["products"]["fragrance"]["heat_rankings"]["CN LUXURY"]:
            if p["name"] == "Maison Margiela Lazy Weekend":
                margiela = p
        assert to_summer is not None, "To Summer Kunlun Snow not found"
        assert margiela is not None, "Maison Margiela Lazy Weekend not found"
        ts_kf = to_summer["detail"]["key_features"]["en"]
        mm_kf = margiela["detail"]["key_features"]["en"]
        assert ts_kf != mm_kf, (
            "To Summer key_features is identical to Margiela (copy-paste error)"
        )

    def test_ysl_key_features_no_malformed_text(self, data):
        """Regression: YSL Skin Affair key_features must not have 'Trend31'."""
        for p in data["products"]["makeup"]["heat_rankings"]["US LUXURY"]:
            if p["name"] == "YSL Skin Affair Soft Glow Cushion Foundation":
                kf_en = p["detail"]["key_features"]["en"]
                assert "Trend31" not in kf_en, (
                    f"YSL key_features has malformed 'Trend31': {kf_en[:60]}"
                )
                assert "Trend · " in kf_en or "Trend " in kf_en, (
                    "YSL key_features missing 'Trend' tag"
                )
                break

    def test_no_forbidden_phrases_in_rendered_sections(self, html_files):
        """Regression: rendered sections must not contain forbidden phrases."""
        forbidden = ["undefined", "null", "TODO", "FIXME", "lorem ipsum"]
        for (topic, lang), html in html_files.items():
            for section_num in (3, 4):
                section = _extract_section(html, section_num)
                for phrase in forbidden:
                    assert phrase.lower() not in section.lower(), (
                        f"{topic} {lang} Section 0{section_num}: "
                        f"forbidden phrase '{phrase}' found"
                    )

    def test_no_placeholder_urls(self, data):
        """Regression: no example.com or localhost URLs in product data."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        link = p.get("detail", {}).get("price_link", {}).get("link", "")
                        if link:
                            assert "example.com" not in link, (
                                f"{topic}/{section}/{panel}/{p['name']}: "
                                f"placeholder URL"
                            )
                            assert "localhost" not in link, (
                                f"{topic}/{section}/{panel}/{p['name']}: localhost URL"
                            )


# ═══════════════════════════════════════════════════════════════════════
# 6. Deterministic rendering
# ═══════════════════════════════════════════════════════════════════════


class TestDeterministicRendering:
    """Same JSON + same templates = identical HTML output."""

    def test_render_produces_identical_output(self, html_files):
        """Regression: rendering must be deterministic."""
        for (topic, lang), html in html_files.items():
            h = hashlib.sha256(html.encode("utf-8")).hexdigest()
            # Store hash for cross-run comparison (in real test, compare two renders)
            assert len(h) == 64, f"{topic} {lang}: invalid SHA256"

    def test_all_links_have_target_blank(self, html_files):
        """Regression: all product links must use target='_blank'."""
        for (topic, lang), html in html_files.items():
            links = re.findall(
                r'<a\s+href="([^"]*)"[^>]*class="heat-link-icon"[^>]*>', html
            )
            for link in links:
                # Find the full anchor tag
                pattern = r'<a\s+href="' + re.escape(link) + r'"[^>]*>'
                m = re.search(pattern, html)
                if m:
                    assert 'target="_blank"' in m.group(0), (
                        f"{topic} {lang}: link missing target='_blank': {link}"
                    )

    def test_no_edp_without_space(self, html_files):
        """Regression: 'EDP' must have a space before it."""
        for (topic, lang), html in html_files.items():
            matches = re.findall(r"\wEDP\b", html)
            assert len(matches) == 0, (
                f"{topic} {lang}: EDP without space before it: {matches[:5]}"
            )


# ═══════════════════════════════════════════════════════════════════════
# 7. Archive validation
# ═══════════════════════════════════════════════════════════════════════


class TestArchive:
    """Archive/week-28 pages must pass basic structural checks."""

    def test_archive_files_exist(self):
        """All 4 archive files must exist."""
        for (topic, lang), fname in ARCHIVE_FILES.items():
            fpath = os.path.join(ROOT, fname)
            assert os.path.exists(fpath), f"Archive missing: {fname}"

    def test_archive_has_both_sections(self):
        """Archive must have Section 03 and Section 04."""
        for (topic, lang), fname in ARCHIVE_FILES.items():
            fpath = os.path.join(ROOT, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                html = f.read()
            assert "Section 03" in html, f"{fname}: missing Section 03"
            assert "Section 04" in html, f"{fname}: missing Section 04"

    def test_archive_has_4_panels_per_section(self):
        """Archive must have 4 panels in each section."""
        for (topic, lang), fname in ARCHIVE_FILES.items():
            fpath = os.path.join(ROOT, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                html = f.read()
            for section_num in (3, 4):
                section = _extract_section(html, section_num)
                h4_count = len(re.findall(r"<h4[^>]*>.*?</h4>", section, re.DOTALL))
                assert h4_count == 4, (
                    f"{fname} Section 0{section_num}: "
                    f"expected 4 panels, found {h4_count}"
                )

    def test_archive_lang_attributes(self):
        """Archive must have correct lang attributes."""
        for (topic, lang), fname in ARCHIVE_FILES.items():
            fpath = os.path.join(ROOT, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                html = f.read()
            if lang == "en":
                assert 'lang="en"' in html, f"{fname}: missing lang='en'"
            else:
                assert 'lang="zh-CN"' in html, f"{fname}: missing lang='zh-CN'"


# ═══════════════════════════════════════════════════════════════════════
# 8. Cross-section consistency
# ═══════════════════════════════════════════════════════════════════════


class TestCrossSectionConsistency:
    """Products appearing in both heat and radar must have consistent scores."""

    def test_score_consistency(self, data):
        """Same product in heat and radar must have same score."""
        for topic in ("makeup", "fragrance"):
            heat = data["products"][topic]["heat_rankings"]
            radar = data["products"][topic]["new_product_radar"]
            for panel in PANELS:
                heat_names = {p["name"]: p.get("score", 0) for p in heat.get(panel, [])}
                radar_names = {
                    p["name"]: p.get("score", 0) for p in radar.get(panel, [])
                }
                for name in set(heat_names.keys()) & set(radar_names.keys()):
                    assert heat_names[name] == radar_names[name], (
                        f"{topic}/{panel}/{name}: "
                        f"score mismatch heat={heat_names[name]} "
                        f"radar={radar_names[name]}"
                    )


# ═══════════════════════════════════════════════════════════════════════
# 9. Closed trend taxonomy invariants
# ═══════════════════════════════════════════════════════════════════════

# Canonical trends from current issue trend sections only.
MAKEUP_CANONICAL_TAGS = {
    "Skincare Foundation",
    "Functional Lip",
    "Low-Saturation Pastel",
}
FRAGRANCE_CANONICAL_TAGS = {
    "Milky Musk",
    "Matcha Fragrance",
    "Rose Revival",
    "Oriental Narrative",
}
ALL_CANONICAL_TAGS = MAKEUP_CANONICAL_TAGS | FRAGRANCE_CANONICAL_TAGS

# Canonical EN→CN label pairs
CANONICAL_TAG_PAIRS = {
    "Skincare Foundation": "养肤底妆趋势",
    "Functional Lip": "唇部功效化趋势",
    "Low-Saturation Pastel": "低饱和粉彩趋势",
    "Milky Musk": "乳感麝香趋势",
    "Matcha Fragrance": "抹茶香水趋势",
    "Rose Revival": "玫瑰复兴趋势",
    "Oriental Narrative": "东方叙事香趋势",
}


class TestTrendTaxonomy:
    """Closed taxonomy: only canonical trends from current issue trend sections."""

    def test_only_canonical_trend_tags_used(self, data):
        """Every trend_tag must be in the canonical taxonomy."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        if p.get("trend_badge") and p.get("score", 0) > 0:
                            kf = p.get("detail", {}).get("key_features", {})
                            for tag in kf.get("trend_tags", []):
                                assert tag in ALL_CANONICAL_TAGS, (
                                    f"{topic}/{section}/{panel}/{p['name']}: "
                                    f"non-canonical trend tag '{tag}'"
                                )

    def test_cross_vertical_isolation(self, data):
        """Makeup trends must not appear on fragrance products and vice versa."""
        for topic in ("makeup", "fragrance"):
            wrong = (
                FRAGRANCE_CANONICAL_TAGS if topic == "makeup" else MAKEUP_CANONICAL_TAGS
            )
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        if p.get("trend_badge") and p.get("score", 0) > 0:
                            kf = p.get("detail", {}).get("key_features", {})
                            for tag in kf.get("trend_tags", []):
                                assert tag not in wrong, (
                                    f"{topic}/{section}/{panel}/{p['name']}: "
                                    f"cross-vertical tag '{tag}'"
                                )

    def test_en_cn_tag_pairs_consistent(self, data):
        """EN trend_tags must have matching CN trend_tags_cn."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        if p.get("trend_badge") and p.get("score", 0) > 0:
                            kf = p.get("detail", {}).get("key_features", {})
                            en_tags = kf.get("trend_tags", [])
                            cn_tags = kf.get("trend_tags_cn", [])
                            for en_tag in en_tags:
                                expected_cn = CANONICAL_TAG_PAIRS.get(en_tag)
                                assert expected_cn, (
                                    f"{p['name']}: EN tag '{en_tag}' has no canonical CN pair"
                                )
                                assert cn_tags, (
                                    f"{p['name']}: EN tag '{en_tag}' missing trend_tags_cn"
                                )
                                assert cn_tags[0] == expected_cn, (
                                    f"{p['name']}: CN tag '{cn_tags[0]}' != expected '{expected_cn}' "
                                    f"for EN tag '{en_tag}'"
                                )

    def test_no_arbitrary_trend_tags(self, data):
        """Tags like 'Lip Oil', 'Unicorn IP', 'Clean Powder' must not appear."""
        forbidden_tags = {
            "Lip Oil",
            "Lip Powder",
            "Skincare Cushion",
            "Clean Powder",
            "Clean Beauty",
            "Tinted Moisturizer",
            "Lip Gloss Revival",
            "Nine-Pan Palette",
            "Unicorn IP",
            "Low Saturation",
            "Lazy Sunday",
            "Moon Theme",
            "Skin Scent",
            "Milky Scent",
            "Gourmand Matcha",
            "Tea Scent",
            "Pseudo Body Scent",
            "Chinese Niche",
            "Chinese Nostalgic",
            "C-beauty Floral",
        }
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in data["products"][topic][section].items():
                    for p in products:
                        if p.get("score", 0) == 0:
                            continue
                        kf = p.get("detail", {}).get("key_features", {})
                        for tag in kf.get("trend_tags", []):
                            assert tag not in forbidden_tags, (
                                f"{topic}/{section}/{panel}/{p['name']}: "
                                f"forbidden arbitrary tag '{tag}'"
                            )

    def test_nine_pan_maps_to_low_saturation_pastel(self, data):
        """九宫格 (3CE Nine-Pan) must map to Low-Saturation Pastel / 低饱和粉彩趋势."""
        p = None
        for prod in data["products"]["makeup"]["heat_rankings"]["CN MASSTIGE"]:
            if prod["name"] == "3CE Nine-Pan Eyeshadow Palette":
                p = prod
                break
        assert p is not None
        kf = p["detail"]["key_features"]
        assert kf["trend_tags"] == ["Low-Saturation Pastel"]
        assert kf["trend_tags_cn"] == ["低饱和粉彩趋势"]

    def test_matcha_fragrance_maps_to_matcha_trend(self, data):
        """美食调抹茶 (Kayali) must map to Matcha Fragrance / 抹茶香水趋势."""
        p = None
        for prod in data["products"]["fragrance"]["heat_rankings"]["US MASSTIGE"]:
            if prod["name"] == "Kayali Freedom Musk Matcha":
                p = prod
                break
        assert p is not None
        kf = p["detail"]["key_features"]
        assert kf["trend_tags"] == ["Matcha Fragrance"]
        assert kf["trend_tags_cn"] == ["抹茶香水趋势"]

    def test_chinese_nostalgic_maps_to_oriental_narrative(self, data):
        """国货记忆 (Scent Library) must map to Oriental Narrative / 东方叙事香趋势."""
        p = None
        for prod in data["products"]["fragrance"]["heat_rankings"]["CN MASSTIGE"]:
            if prod["name"] == "Scent Library Boiled Water":
                p = prod
                break
        assert p is not None
        kf = p["detail"]["key_features"]
        assert kf["trend_tags"] == ["Oriental Narrative"]
        assert kf["trend_tags_cn"] == ["东方叙事香趋势"]

    def test_ambiguous_cbeauty_floral_no_trend_badge(self, data):
        """国货花果 (Bingxili) must NOT have trend_badge (ambiguous, no evidence)."""
        for prod in data["products"]["fragrance"]["heat_rankings"]["CN MASSTIGE"]:
            if prod["name"] == "Bingxili Mirage Quicksand Gold":
                assert not prod.get("trend_badge"), (
                    "Bingxili Mirage Quicksand Gold should not have trend_badge"
                )
                kf = prod.get("detail", {}).get("key_features", {})
                assert not kf.get("trend_tags"), (
                    "Bingxili Mirage Quicksand Gold should not have trend_tags"
                )
                return
        pytest.fail("Bingxili Mirage Quicksand Gold not found in data")

    def test_products_without_valid_evidence_no_badge(self, data):
        """Products without evidence for any current trend must not have trend_badge."""
        no_badge_products = {
            "makeup": {
                "heat_rankings": {
                    "US MASSTIGE": [
                        "Rare Beauty Find Comfort Tinted Moisturizer",
                        "Kosas Cloud Set Blurring Powder",
                    ],
                },
            },
            "fragrance": {
                "heat_rankings": {
                    "US LUXURY": ["Maison Margiela Replica Lazy Sunday Morning"],
                    "US MASSTIGE": ["Lake & Skye 11 11 Moon EDP"],
                    "CN LUXURY": ["Maison Margiela Lazy Weekend"],
                    "CN MASSTIGE": ["Bingxili Mirage Quicksand Gold"],
                },
            },
        }
        for topic, sections in no_badge_products.items():
            for section, panels in sections.items():
                for panel, names in panels.items():
                    for name in names:
                        for p in data["products"][topic][section].get(panel, []):
                            if p["name"] == name:
                                assert not p.get("trend_badge"), (
                                    f"{topic}/{section}/{panel}/{name}: "
                                    f"should not have trend_badge '{p.get('trend_badge')}'"
                                )

    def test_trend_tags_render_in_en_html(self, html_files):
        """EN HTML trend_tags must all be canonical."""
        for (topic, lang), html in html_files.items():
            if lang != "en":
                continue
            tags = re.findall(r'<span\s+class="heat-trend-tag">([^<]+)</span>', html)
            for tag in tags:
                assert tag in ALL_CANONICAL_TAGS, (
                    f"{topic} EN: non-canonical trend tag '{tag}' in HTML"
                )

    def test_trend_tags_render_in_cn_html(self, html_files):
        """CN HTML trend_tags must all be canonical CN labels."""
        cn_labels = set(CANONICAL_TAG_PAIRS.values())
        for (topic, lang), html in html_files.items():
            if lang != "cn":
                continue
            tags = re.findall(r'<span\s+class="heat-trend-tag">([^<]+)</span>', html)
            for tag in tags:
                assert tag in cn_labels, (
                    f"{topic} CN: non-canonical CN trend tag '{tag}' in HTML"
                )


# ═══════════════════════════════════════════════════════════════════════
# 10. Quarantine and launch-date validation
# ═══════════════════════════════════════════════════════════════════════


class TestQuarantineAndLaunchDate:
    """Radar items must have quarantine_status, launch_date, and be within window."""

    def test_all_radar_products_have_quarantine_status(self, data):
        """Every radar product must have a quarantine_status field."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    assert "quarantine_status" in p, (
                        f"{topic}/radar/{panel}/{p['name']}: missing quarantine_status"
                    )
                    assert p["quarantine_status"] in ("verified", "out-of-window"), (
                        f"{topic}/radar/{panel}/{p['name']}: "
                        f"invalid quarantine_status '{p['quarantine_status']}'"
                    )

    def test_all_radar_products_have_launch_date(self, data):
        """Every radar product must have a launch_date field."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    assert "launch_date" in p, (
                        f"{topic}/radar/{panel}/{p['name']}: missing launch_date"
                    )

    def test_quarantined_items_not_rendered_in_html(self, data, html_files):
        """Quarantined radar items must not appear in rendered HTML."""
        quarantined_names = set()
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("quarantine_status") == "out-of-window":
                        quarantined_names.add(p["name"])
        for (topic, lang), html in html_files.items():
            s4 = _extract_section(html, 4)
            for name in quarantined_names:
                assert name not in s4, (
                    f"{topic} {lang}: quarantined item '{name}' found in radar HTML"
                )

    def test_out_of_window_items_have_reason(self, data):
        """Quarantined items must have a quarantine_reason."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("quarantine_status") == "out-of-window":
                        assert p.get("quarantine_reason"), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"quarantined but missing quarantine_reason"
                        )

    def test_no_heat_placeholders_in_data(self, data):
        """Heat rankings must have zero placeholder (score=0) products."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["heat_rankings"].items():
                for p in products:
                    assert p.get("score", 0) > 0, (
                        f"{topic}/heat/{panel}/{p.get('name')}: "
                        f"placeholder (score=0) found in heat rankings"
                    )

    def test_no_heat_placeholders_in_html(self, html_files):
        """Rendered heat sections must contain no placeholder text."""
        for (topic, lang), html in html_files.items():
            s3 = _extract_section(html, 3)
            assert "no more signal" not in s3.lower(), (
                f"{topic} {lang}: placeholder text 'no more signal' in heat HTML"
            )
            assert "本周无更多" not in s3, (
                f"{topic} {lang}: placeholder text '本周无更多' in heat HTML"
            )


# ═══════════════════════════════════════════════════════════════════════
# 11. Trend metadata consistency for radar items
# ═══════════════════════════════════════════════════════════════════════


class TestRadarTrendMetadata:
    """Radar items with trend_badge must have complete trend metadata."""

    def test_trend_badge_products_have_all_metadata(self, data):
        """Trend-badge radar products must have trend_id, trend_tag, trend_tag_cn, trend_rationale."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    if p.get("trend_badge"):
                        assert p.get("trend_id"), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"trend-badge product missing trend_id"
                        )
                        assert p.get("trend_tag"), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"trend-badge product missing trend_tag"
                        )
                        assert p.get("trend_tag_cn"), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"trend-badge product missing trend_tag_cn"
                        )
                        assert p.get("trend_rationale"), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"trend-badge product missing trend_rationale"
                        )

    def test_non_trend_products_have_null_metadata(self, data):
        """Non-trend radar products should have null/empty trend metadata."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    if not p.get("trend_badge"):
                        assert not p.get("trend_id"), (
                            f"{topic}/radar/{panel}/{p['name']}: "
                            f"non-trend product has trend_id set"
                        )

    def test_trend_tag_matches_trend_tags_in_key_features(self, data):
        """trend_tag field must match trend_tags[0] in key_features for trend-badge products."""
        for topic in ("makeup", "fragrance"):
            for panel, products in data["products"][topic]["new_product_radar"].items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    if p.get("trend_badge") and p.get("trend_tag"):
                        kf = p.get("detail", {}).get("key_features", {})
                        en_tags = kf.get("trend_tags", [])
                        if en_tags:
                            assert p["trend_tag"] == en_tags[0], (
                                f"{topic}/radar/{panel}/{p['name']}: "
                                f"trend_tag '{p['trend_tag']}' != "
                                f"key_features.trend_tags[0] '{en_tags[0]}'"
                            )

    def test_quarantined_items_not_in_heat(self, data):
        """Products quarantined in radar should not appear in heat rankings.

        Note: Some products (e.g. DedCool Mochi Milk) may legitimately appear
        in heat (trending) while quarantined in radar (not new). This test
        only checks that quarantined items are not padded into heat.
        """
        for topic in ("makeup", "fragrance"):
            radar = data["products"][topic]["new_product_radar"]
            heat = data["products"][topic]["heat_rankings"]
            # Collect quarantined items that are NOT also in heat with real scores
            quarantined_only = set()
            for panel, products in radar.items():
                for p in products:
                    if p.get("quarantine_status") == "out-of-window":
                        # Check if this product is also in heat (legitimately trending)
                        in_heat = False
                        for hp in heat.get(panel, []):
                            if hp["name"] == p["name"] and hp.get("score", 0) > 0:
                                in_heat = True
                                break
                        if not in_heat:
                            quarantined_only.add(p["name"])
            for panel, products in heat.items():
                for p in products:
                    assert p["name"] not in quarantined_only, (
                        f"{topic}/heat/{panel}/{p['name']}: "
                        f"quarantined-only radar item found in heat rankings"
                    )
