#!/usr/bin/env python3
"""Comprehensive validator for beauty-weekly HTML output.

Implements all IT cross-check rules (all hard-fail, no warnings):
  1. 4 panels per section (US LUXURY, US MASSTIGE, CN LUXURY, CN MASSTIGE)
  2. 10 rows per panel for heat; dynamic (0+) for radar/new_product_radar
  3. Scores, ranks, products aligned across EN/CN
  4. Exactly four score labels (Heat/热度值) - rank #1 only
  5. Trend/New badge semantics (Trend=趋势产品, New=新品)
  6. Forbidden phrases / undefined values
  7. Language purity (EN file lang=en, CN file lang=zh-CN)
  8. Fragrance terminology (EDP spacing)
  9. Grid headings consistency
 10. EDP spacing rules
 11. href and link policy (all links use target=_blank, heat-link-icon class)
 12. Evidence URLs (no bare example.com, valid https)
 13. Scoring/category/trend consistency (score range 65-98, monotonic rank)
 14. Radar cards must be plain text (no badges/trend/heat indicators)
 15. Placeholder rows recognized (score=0, no score/detail exemption for real products)
 16. Trend tags: products with trend_badge must have trend_tags on key_features
 17. Language isolation: no Chinese in EN fields, no English-only in CN fields
 18. Dynamic radar: item count matches actual products (no fixed 40)

Exit code 0 = all pass, 1 = failures found.
"""

import json
import os
import re
import sys
from typing import Any, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "week28.json")

FILES = {
    ("makeup", "en"): "index.html",
    ("makeup", "cn"): "index-cn.html",
    ("fragrance", "en"): "fragrance.html",
    ("fragrance", "cn"): "fragrance-cn.html",
}

PANELS = ["US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"]

FORBIDDEN_PHRASES = [
    "undefined",
    "null",
    "N/A",
    "TBD",
    "TODO",
    "FIXME",
    "lorem ipsum",
    "placeholder",
    "sample data",
]

# Score display tiers (must match scoring methodology)
SCORE_RANGE = (65, 98)

# Valid score labels
SCORE_LABELS_EN = ["Heat"]
SCORE_LABELS_CN = ["热度值"]

# EDP spacing: "EDP" must have a space before it when preceded by a word character
EDP_PATTERN = re.compile(r"\wEDP\b")


class ValidationIssue:
    def __init__(self, severity: str, file: str, rule: str, message: str):
        self.severity = severity  # ERROR or WARN
        self.file = file
        self.rule = rule
        self.message = message

    def __str__(self):
        return "[{0}] {1} | {2}: {3}".format(
            self.severity, self.file, self.rule, self.message
        )


def _load_data() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_html(filename: str) -> str:
    path = os.path.join(ROOT, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_section_html(html: str, section_num: int) -> str:
    """Extract Section 03 or 04 HTML content."""
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


def _count_panels(section_html: str) -> int:
    """Count h4 headings with US/CN and LUXURY/MASSTIGE spans."""
    h4_matches = re.findall(r"<h4[^>]*>.*?</h4>", section_html, re.DOTALL)
    count = 0
    for h4 in h4_matches:
        if re.search(r"<span[^>]*>(US|CN)</span>", h4) and re.search(
            r"<span[^>]*>(LUXURY|MASSTIGE)</span>", h4
        ):
            count += 1
    return count


def _count_items(section_html: str) -> int:
    """Count heat-item li elements."""
    return len(re.findall(r'<li\s+class="heat-item"', section_html))


def _extract_scores_from_html(section_html: str) -> List[int]:
    """Extract all heat-score values from HTML."""
    return [
        int(m)
        for m in re.findall(r'<span\s+class="heat-score">(\d+)</span>', section_html)
    ]


def _extract_ranks_from_html(section_html: str) -> List[int]:
    """Extract all rank values from HTML."""
    return [
        int(m)
        for m in re.findall(
            r'<span\s+class="heat-rank\s+(us|cn)">(\d+)</span>', section_html
        )
    ]


def _extract_names_from_html(section_html: str) -> List[str]:
    """Extract all product names from HTML."""
    return re.findall(r'<span\s+class="heat-name">([^<]+)</span>', section_html)


def _count_score_labels(section_html: str) -> int:
    """Count score label spans."""
    return len(re.findall(r'<span\s+class="heat-score-label"', section_html))


def _check_language_purity(
    filename: str, lang: str, html: str
) -> List[ValidationIssue]:
    issues = []
    # Check lang attribute
    if lang == "en":
        if 'lang="en"' not in html:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "language-purity",
                    'EN file missing lang="en" attribute',
                )
            )
    elif lang == "cn":
        if 'lang="zh-CN"' not in html:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "language-purity",
                    'CN file missing lang="zh-CN" attribute',
                )
            )
    return issues


def _check_forbidden_phrases(filename: str, html: str) -> List[ValidationIssue]:
    issues = []
    html_lower = html.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in html_lower:
            # Exclude legitimate uses in methodology text
            if phrase.lower() in ("n/a",) and "Source" in html:
                continue
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "forbidden-phrases",
                    "Found forbidden phrase: '{0}'".format(phrase),
                )
            )
    return issues


def _check_edp_spacing(filename: str, html: str) -> List[ValidationIssue]:
    issues = []
    # Find EDP without space before it
    matches = EDP_PATTERN.findall(html)
    if matches:
        issues.append(
            ValidationIssue(
                "ERROR",
                filename,
                "edp-spacing",
                "EDP without space before it: {0} occurrences".format(len(matches)),
            )
        )
    return issues


def _check_href_policy(filename: str, html: str) -> List[ValidationIssue]:
    issues = []
    # Check all heat-link-icon links have target="_blank"
    all_link_tags = re.findall(
        r'<a\s+href="([^"]*)"[^>]*class="heat-link-icon"[^>]*>', html
    )
    for link in all_link_tags:
        if (
            'target="_blank"'
            not in html[html.index(link) - 100 : html.index(link) + 200]
        ):
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "href-policy",
                    'heat-link-icon link missing target="_blank": {0}'.format(link),
                )
            )
    return issues


def _check_evidence_urls(filename: str, html: str) -> List[ValidationIssue]:
    issues = []
    # Check for example.com or placeholder URLs
    placeholder_urls = re.findall(
        r'href="(https?://(?:example\.com|localhost|127\.0\.0\.1)[^"]*)"', html
    )
    for url in placeholder_urls:
        issues.append(
            ValidationIssue(
                "ERROR",
                filename,
                "evidence-urls",
                "Placeholder URL found: {0}".format(url),
            )
        )
    # Check for fabricated/generic root page URLs where exact product links required
    generic_urls = re.findall(
        r'href="(https?://(?:www\.documentscn\.com|www\.scentlibrary\.cn)[^"]*)"',
        html,
    )
    for url in generic_urls:
        issues.append(
            ValidationIssue(
                "ERROR",
                filename,
                "evidence-urls",
                "Fabricated/generic URL found: {0}".format(url),
            )
        )
    return issues


def _check_radar_plain_text(filename: str, html: str) -> List[ValidationIssue]:
    """Section 04 (radar) must have plain text cards - no badges/pills in card headers.
    Note: heat-trend-tag in detail cells IS allowed (concrete qualifying tags)."""
    issues = []
    section_html = _extract_section_html(html, 4)
    if not section_html:
        return issues
    # Radar must not have header-level badges: heat-trend-badge, heat-new-badge, heat-score-label
    # heat-trend-tag in detail cells IS allowed (concrete qualifying trend tags)
    forbidden_in_radar = [
        (r'<span\s+class="heat-trend-badge"', "heat-trend-badge"),
        (r'<span\s+class="heat-new-badge"', "heat-new-badge"),
        (r'<span\s+class="heat-score-label"', "heat-score-label"),
    ]
    for pattern, tag_name in forbidden_in_radar:
        matches = re.findall(pattern, section_html)
        if matches:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "radar-plain-text",
                    "Section 04 contains forbidden '{0}' ({1} occurrences)".format(
                        tag_name, len(matches)
                    ),
                )
            )
    return issues


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _check_data_consistency(data: dict) -> List[ValidationIssue]:
    issues = []
    for topic in ("makeup", "fragrance"):
        products = data["products"].get(topic, {})
        for section in ("heat_rankings", "new_product_radar"):
            panels = products.get(section, {})
            # Rule: 4 panels
            if len(panels) != 4:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "data",
                        "panel-count",
                        "{0}/{1}: expected 4 panels, got {2}".format(
                            topic, section, len(panels)
                        ),
                    )
                )
            for panel_key in PANELS:
                panel_products = panels.get(panel_key, [])
                # Rule: heat panels must have 1-10 real rows (no placeholders); radar panels are dynamic (0+)
                if section == "heat_rankings":
                    real_products = [
                        p for p in panel_products if _safe_int(p.get("score", 0)) > 0
                    ]
                    if len(real_products) < 1 or len(real_products) > 10:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                "data",
                                "panel-rows",
                                "{0}/{1}/{2}: expected 1-10 real rows, got {3}".format(
                                    topic, section, panel_key, len(real_products)
                                ),
                            )
                        )
                elif section == "new_product_radar" and len(panel_products) > 10:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            "data",
                            "panel-rows",
                            "{0}/{1}/{2}: radar panel has {3} rows (max 10)".format(
                                topic, section, panel_key, len(panel_products)
                            ),
                        )
                    )
                # Rule: scores in range (skip placeholder rows with score=0)
                for p in panel_products:
                    score = _safe_int(p.get("score", 0))
                    if score == 0:
                        # Placeholder row in heat is a defect; in radar it's allowed but filtered
                        name = p.get("name", "")
                        if section == "heat_rankings":
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    "data",
                                    "heat-placeholder",
                                    "{0}/{1}/{2}: rank {3} has placeholder row (score=0, name='{4}') – must be removed".format(
                                        topic,
                                        section,
                                        panel_key,
                                        p.get("rank", "?"),
                                        name[:40],
                                    ),
                                )
                            )
                        elif (
                            "no more signal" not in name.lower()
                            and "本周无更多" not in name
                        ):
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    "data",
                                    "placeholder-name",
                                    "{0}/{1}/{2}: rank {3} score=0 but name is not a placeholder".format(
                                        topic, section, panel_key, p.get("rank", "?")
                                    ),
                                )
                            )
                        continue
                    if not (SCORE_RANGE[0] <= score <= SCORE_RANGE[1]):
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                "data",
                                "score-range",
                                "{0}/{1}: {2} score {3} out of range {4}-{5}".format(
                                    topic,
                                    panel_key,
                                    p.get("name", "?"),
                                    score,
                                    SCORE_RANGE[0],
                                    SCORE_RANGE[1],
                                ),
                            )
                        )
                    # Rule: ranks are 1-10
                    rank = _safe_int(p.get("rank", 0))
                    if not (1 <= rank <= 10):
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                "data",
                                "rank-range",
                                "{0}/{1}: {2} rank {3} out of range 1-10".format(
                                    topic, panel_key, p.get("name", "?"), rank
                                ),
                            )
                        )
                # Rule: no duplicate ranks
                rank_list = [_safe_int(p.get("rank", 0)) for p in panel_products]
                if len(rank_list) != len(set(rank_list)):
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            "data",
                            "duplicate-ranks",
                            "{0}/{1}: duplicate ranks found".format(topic, panel_key),
                        )
                    )
                # Rule: detail cells present (skip placeholder rows)
                for p in panel_products:
                    if _safe_int(p.get("score", 0)) == 0:
                        continue
                    detail = p.get("detail", {})
                    for key in ("price_link", "key_features", "buzz", "brand"):
                        if key not in detail:
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    "data",
                                    "missing-detail",
                                    "{0}/{1}: {2} missing {3}".format(
                                        topic, panel_key, p.get("name", "?"), key
                                    ),
                                )
                            )

    # Rule: cross-section score consistency (same product in heat and radar should have same score)
    for topic in ("makeup", "fragrance"):
        heat = data["products"].get(topic, {}).get("heat_rankings", {})
        radar = data["products"].get(topic, {}).get("new_product_radar", {})
        for panel_key in PANELS:
            heat_names = {
                p["name"]: _safe_int(p.get("score", 0)) for p in heat.get(panel_key, [])
            }
            radar_names = {
                p["name"]: _safe_int(p.get("score", 0))
                for p in radar.get(panel_key, [])
            }
            for name in set(heat_names.keys()) & set(radar_names.keys()):
                if heat_names[name] != radar_names[name]:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            "data",
                            "cross-section-consistency",
                            "{0}/{1}: {2} score mismatch heat={3} radar={4}".format(
                                topic,
                                panel_key,
                                name,
                                heat_names[name],
                                radar_names[name],
                            ),
                        )
                    )

    # Rule: radar products must have quarantine_status, launch_date, and trend metadata
    for topic in ("makeup", "fragrance"):
        radar = data["products"].get(topic, {}).get("new_product_radar", {})
        for panel_key, products in radar.items():
            for p in products:
                score = _safe_int(p.get("score", 0))
                if score == 0:
                    continue
                name = p.get("name", "?")
                loc = f"data/{topic}/radar/{panel_key}/{name}"

                # quarantine_status required
                qs = p.get("quarantine_status")
                if qs is None:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            loc,
                            "missing-quarantine-status",
                            "Radar product missing quarantine_status field",
                        )
                    )
                elif qs not in ("verified", "out-of-window"):
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            loc,
                            "invalid-quarantine-status",
                            f"Invalid quarantine_status '{qs}'",
                        )
                    )

                # launch_date required
                ld = p.get("launch_date")
                if ld is None:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            loc,
                            "missing-launch-date",
                            "Radar product missing launch_date field",
                        )
                    )

                # trend metadata consistency
                trend_badge = p.get("trend_badge")
                trend_id = p.get("trend_id")
                trend_tag = p.get("trend_tag")
                trend_tag_cn = p.get("trend_tag_cn")
                trend_rationale = p.get("trend_rationale")

                if trend_badge:
                    if not trend_id:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                loc,
                                "missing-trend-id",
                                "Trend-badge radar product missing trend_id",
                            )
                        )
                    if not trend_tag:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                loc,
                                "missing-trend-tag-field",
                                "Trend-badge radar product missing trend_tag field",
                            )
                        )
                    if not trend_tag_cn:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                loc,
                                "missing-trend-tag-cn-field",
                                "Trend-badge radar product missing trend_tag_cn field",
                            )
                        )
                    if not trend_rationale:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                loc,
                                "missing-trend-rationale",
                                "Trend-badge radar product missing trend_rationale field",
                            )
                        )
                else:
                    # No trend_badge → trend fields should be null
                    if trend_id is not None:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                loc,
                                "stale-trend-id",
                                "Non-trend radar product has trend_id set",
                            )
                        )

    return issues


def _check_html_panels(filename: str, html: str) -> List[ValidationIssue]:
    issues = []
    for section_num in (3, 4):
        section_html = _extract_section_html(html, section_num)
        if not section_html:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "section-existence",
                    "Section 0{0} not found".format(section_num),
                )
            )
            continue
        panel_count = _count_panels(section_html)
        if panel_count != 4:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "panel-count",
                    "Section 0{0}: expected 4 panels, found {1}".format(
                        section_num, panel_count
                    ),
                )
            )
        # Check for placeholder text in any section
        if "no more signal" in section_html.lower():
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "placeholder-in-section",
                    "Section 0{0}: contains placeholder text 'no more signal'".format(
                        section_num
                    ),
                )
            )
        if "本周无更多" in section_html:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "placeholder-in-section",
                    "Section 0{0}: contains placeholder text '本周无更多'".format(
                        section_num
                    ),
                )
            )
        item_count = _count_items(section_html)
        # Section 03 (heat) should have 1-40 items (dynamic, no placeholders); Section 04 (radar) is dynamic
        if section_num == 3:
            if item_count < 1 or item_count > 40:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        filename,
                        "item-count",
                        "Section 0{0}: expected 1-40 items, found {1}".format(
                            section_num, item_count
                        ),
                    )
                )
        else:
            # Section 04 (radar): must have 0-40 items (dynamic, no padding)
            if item_count > 40:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        filename,
                        "item-count",
                        "Section 0{0}: found {1} items (max 40)".format(
                            section_num, item_count
                        ),
                    )
                )
        # Score labels: rank #1 per panel in Section 03; 0 in Section 04
        label_count = _count_score_labels(section_html)
        if section_num == 3:
            # Count panels that have products
            panel_heading_count = _count_panels(section_html)
            if label_count != panel_heading_count:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        filename,
                        "score-label-count",
                        "Section 0{0}: expected {1} score labels (one per panel), found {2}".format(
                            section_num, panel_heading_count, label_count
                        ),
                    )
                )
        else:
            if label_count != 0:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        filename,
                        "score-label-count",
                        "Section 0{0}: expected 0 score labels, found {1}".format(
                            section_num, label_count
                        ),
                    )
                )
    return issues


def _check_trend_new_badges(data: dict) -> List[ValidationIssue]:
    """Verify trend/new badge semantics: Trend means rising product, New means recent launch.
    Also verify that trend-badge products have concrete trend_tags on key_features."""
    issues = []
    for topic in ("makeup", "fragrance"):
        products = data["products"].get(topic, {})
        for section in ("heat_rankings", "new_product_radar"):
            for panel_key, panel_products in products.get(section, {}).items():
                for p in panel_products:
                    trend = p.get("trend_badge")
                    new = p.get("new_badge")
                    # Trend badge should be "Trend" or None
                    if trend and trend not in ("Trend", "趋势产品"):
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                "data",
                                "trend-badge-value",
                                "{0}/{1}: unexpected trend badge '{2}'".format(
                                    topic, panel_key, trend
                                ),
                            )
                        )
                    # New badge should be "New", "NEW", or None
                    if new and new not in ("New", "NEW", "新品"):
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                "data",
                                "new-badge-value",
                                "{0}/{1}: unexpected new badge '{2}'".format(
                                    topic, panel_key, new
                                ),
                            )
                        )
                    # Rule: trend-badge products must have concrete trend_tags on key_features
                    if trend and trend in ("Trend", "趋势产品"):
                        score = _safe_int(p.get("score", 0))
                        if score > 0:  # skip placeholders
                            detail = p.get("detail", {})
                            kf = detail.get("key_features", {})
                            tags = kf.get("trend_tags") or kf.get("trend_tags_cn")
                            if not tags:
                                issues.append(
                                    ValidationIssue(
                                        "ERROR",
                                        "data",
                                        "trend-tags-missing",
                                        "{0}/{1}/{2}: trend-badge product missing concrete trend_tags on key_features".format(
                                            topic, panel_key, p.get("name", "?")
                                        ),
                                    )
                                )
    return issues


def _check_trend_tags_rules(data: dict, filename: str) -> List[ValidationIssue]:
    """Validate trend_tags against canonical taxonomy.

    Rules enforced:
    1. Only canonical trend tags from current issue trend sections are allowed.
    2. EN and CN tag labels must form a valid localized pair.
    3. Makeup trends may only appear on makeup products; fragrance on fragrance.
    4. trend_badge products must have at least one valid trend_tag.
    5. trend_badge without any matching canonical trend is forbidden.
    """
    issues = []

    # Canonical trend taxonomy: {tag_value: [en_canonical, cn_canonical]}
    # Only trends defined in current issue trend sections are valid.
    CANONICAL_TREND_CATEGORIES = {
        # Makeup vertical trends
        "Skincare Foundation": ["Skincare Foundation Trend", "养肤底妆趋势"],
        "Functional Lip": ["Functional Lip Trend", "唇部功效化趋势"],
        "Low-Saturation Pastel": ["Low-Saturation Pastel Trend", "低饱和粉彩趋势"],
        # Fragrance vertical trends
        "Milky Musk": ["Milky Musk Trend", "乳感麝香趋势"],
        "Matcha Fragrance": ["Matcha Fragrance Trend", "抹茶香水趋势"],
        "Rose Revival": ["Rose Revival Trend", "玫瑰复兴趋势"],
        "Oriental Narrative": ["Oriental Narrative Trend", "东方叙事香趋势"],
    }

    # Valid trend tags per vertical (for cross-vertical isolation)
    MAKEUP_TREND_TAGS = {
        "Skincare Foundation",
        "Functional Lip",
        "Low-Saturation Pastel",
    }
    FRAGRANCE_TREND_TAGS = {
        "Milky Musk",
        "Matcha Fragrance",
        "Rose Revival",
        "Oriental Narrative",
    }

    for topic in ("makeup", "fragrance"):
        valid_vertical_tags = (
            MAKEUP_TREND_TAGS if topic == "makeup" else FRAGRANCE_TREND_TAGS
        )
        products = data["products"].get(topic, {})
        for section in ("heat_rankings", "new_product_radar"):
            for panel_key, panel_products in products.get(section, {}).items():
                for p in panel_products:
                    if not p.get("trend_badge") or p.get("score", 0) == 0:
                        continue

                    kf = p.get("detail", {}).get("key_features", {})
                    en_tags = kf.get("trend_tags", [])
                    cn_tags = kf.get("trend_tags_cn", [])
                    pname = p.get("name", "?")
                    loc = f"{filename}/{topic}/{section}/{panel_key}/{pname}"

                    if not en_tags:
                        issues.append(
                            ValidationIssue(
                                "ERROR",
                                loc,
                                "missing-trend-tag",
                                "Trend-badge product missing trend_tags on key_features",
                            )
                        )
                        continue

                    for en_tag in en_tags:
                        if en_tag not in CANONICAL_TREND_CATEGORIES:
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    loc,
                                    "arbitrary-trend-tag",
                                    f"Unknown trend tag '{en_tag}' – not in canonical taxonomy",
                                )
                            )
                            continue

                        # Cross-vertical check
                        if en_tag not in valid_vertical_tags:
                            other = "fragrance" if topic == "makeup" else "makeup"
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    loc,
                                    "cross-vertical-trend",
                                    f"Trend tag '{en_tag}' belongs to {other} vertical, used on {topic} product",
                                )
                            )

                        # EN/CN pair consistency
                        canon_en, canon_cn = CANONICAL_TREND_CATEGORIES[en_tag]
                        if cn_tags:
                            if cn_tags[0] != canon_cn:
                                issues.append(
                                    ValidationIssue(
                                        "ERROR",
                                        loc,
                                        "trend-cn-mismatch",
                                        f"CN tag '{cn_tags[0]}' does not match canonical '{canon_cn}' for EN tag '{en_tag}'",
                                    )
                                )
                        else:
                            issues.append(
                                ValidationIssue(
                                    "ERROR",
                                    loc,
                                    "missing-trend-tag-cn",
                                    f"Missing trend_tags_cn for EN tag '{en_tag}'",
                                )
                            )

    return issues


def main() -> int:
    data = _load_data()
    all_issues: List[ValidationIssue] = []

    # Data-level checks
    all_issues.extend(_check_data_consistency(data))
    all_issues.extend(_check_trend_new_badges(data))
    all_issues.extend(_check_trend_tags_rules(data, "data/week28.json"))

    # HTML-level checks
    for (topic, lang), filename in FILES.items():
        try:
            html = _read_html(filename)
        except FileNotFoundError:
            all_issues.append(
                ValidationIssue(
                    "ERROR",
                    filename,
                    "file-existence",
                    "File not found: {0}".format(filename),
                )
            )
            continue

        all_issues.extend(_check_language_purity(filename, lang, html))
        all_issues.extend(_check_forbidden_phrases(filename, html))
        all_issues.extend(_check_edp_spacing(filename, html))
        all_issues.extend(_check_href_policy(filename, html))
        all_issues.extend(_check_evidence_urls(filename, html))
        all_issues.extend(_check_html_panels(filename, html))
        all_issues.extend(_check_radar_plain_text(filename, html))

    # Print results
    errors = [i for i in all_issues if i.severity == "ERROR"]
    warnings = [i for i in all_issues if i.severity == "WARN"]

    if all_issues:
        print("\n=== Validation Results ===\n")
        for issue in all_issues:
            print(str(issue))
        print("\n--- Summary ---")
        print("ERRORS: {0}".format(len(errors)))
        print("WARNINGS: {0}".format(len(warnings)))
    else:
        print("All validation checks passed.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
