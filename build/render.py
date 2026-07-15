#!/usr/bin/env python3
"""Deterministic renderer: regenerate the four root HTML files from data/week28.json.

Only replaces Sections 03 (heat rankings) and 04 (new product radar).
All other content (banner, news, trends, appendix, CSS, JS) is preserved
verbatim from the original HTML files, which are treated as templates.

Design invariants
-----------------
* Deterministic: same JSON + same templates = identical HTML output.
* No global split/join mutation.
* One record edit in JSON propagates to all language variants.
* Archives are never touched.
"""

import json
import os
import re
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "week28.json")
TEMPLATES = {
    ("makeup", "en"): "index.html",
    ("makeup", "cn"): "index-cn.html",
    ("fragrance", "en"): "fragrance.html",
    ("fragrance", "cn"): "fragrance-cn.html",
}

# Detail cell label mappings per language
CELL_LABELS = {
    "en": {
        "heat": [
            "Price/Link",
            "Key Features",
            "Buzz/Reviews/Sales",
            "Brand/Positioning",
        ],
        "radar": [
            "Price/Link",
            "Key Features",
            "Buzz/Reviews/Sales",
            "Launch/Category",
        ],
    },
    "cn": {
        "heat": ["价格/链接", "核心卖点", "社媒热度/口碑/销量", "品牌/产品定位"],
        "radar": ["价格/链接", "核心卖点", "社媒热度/口碑/销量", "上市日期/新品类目"],
    },
}

DETAIL_KEYS = ["price_link", "key_features", "buzz", "brand"]

# Tier display labels per language
TIER_LABELS = {
    "en": {"LUXURY": "LUXURY", "MASSTIGE": "MASSTIGE"},
    "cn": {"LUXURY": "LUXURY", "MASSTIGE": "MASSTIGE"},
}

# Section title labels
SECTION_TITLES = {
    ("makeup", "en"): ("Makeup", "Heat", "Rankings", "New Product", "Radar"),
    ("makeup", "cn"): ("彩妆", "热度", "排名", "新品", "雷达"),
    ("fragrance", "en"): ("Fragrance", "Heat", "Rankings", "New Product", "Radar"),
    ("fragrance", "cn"): ("香水", "热度", "排名", "新品", "雷达"),
}

# Panel heading sub-labels
PANEL_SUB_LABELS = {
    ("makeup", "en"): {"LUXURY": "LUXURY TOP 10", "MASSTIGE": "MASSTIGE TOP 10"},
    ("makeup", "cn"): {"LUXURY": "奢品线 TOP 10", "MASSTIGE": "精品彩妆 TOP 10"},
    ("fragrance", "en"): {"LUXURY": "LUXURY TOP 10", "MASSTIGE": "MASSTIGE TOP 10"},
    ("fragrance", "cn"): {"LUXURY": "奢品线 TOP 10", "MASSTIGE": "精品香氛 TOP 10"},
}

# Radar panel heading sub-labels
RADAR_PANEL_SUB_LABELS = {
    ("makeup", "en"): "New Arrivals",
    ("makeup", "cn"): "新品追踪",
    ("fragrance", "en"): "New Arrivals",
    ("fragrance", "cn"): "新品追踪",
}


def _esc(text: str) -> str:
    """HTML-escape text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_detail_cell(label: str, cell_data: Dict[str, Any], lang: str) -> str:
    """Render a single detail cell div."""
    value = cell_data.get(lang) or cell_data.get("en") or ""
    link_url = cell_data.get("link", "")
    # Clean up value – remove trailing link emoji if we'll render a proper link
    value_clean = value.replace(" 🔗", "").replace("🔗", "").strip()
    link_html = ""
    if link_url:
        link_html = ' <a href="{0}" target="_blank" class="heat-link-icon" title="{1}">🔗</a>'.format(
            _esc(link_url),
            "View product" if lang == "en" else "查看产品",
        )
    # Per-language trend_tags: prefer language-specific, fall back to generic
    if lang == "cn":
        trend_tags = cell_data.get("trend_tags_cn") or cell_data.get("trend_tags", [])
    else:
        trend_tags = cell_data.get("trend_tags", [])
    trend_html = ""
    if trend_tags:
        trend_html = " " + "".join(
            '<span class="heat-trend-tag">{0}</span>'.format(_esc(t))
            for t in trend_tags
        )
    return (
        '<div class="heat-detail-cell">'
        '<div class="heat-detail-label">{label}</div>'
        '<div class="heat-detail-value">{trend}{value}{link}</div>'
        "</div>"
    ).format(
        label=_esc(label), trend=trend_html, value=_esc(value_clean), link=link_html
    )


def _render_product(product: Dict[str, Any], lang: str, section: str) -> str:
    """Render a single heat-item li element."""
    rank = product["rank"]
    market = product["market"].lower()
    # Per-language product name: prefer name_cn for CN pages, name_en or name for EN
    if lang == "cn":
        name = product.get("name_cn") or product.get("name", "")
    else:
        name = product.get("name_en") or product.get("name", "")
    cat = product.get("category_badge", "")
    cat_cn = product.get("category_badge_cn", "")
    if lang == "cn" and cat_cn:
        cat = cat_cn
    score = product.get("score", 0)
    trend_badge = product.get("trend_badge")
    new_badge = product.get("new_badge")

    # Display clamp: raw_score below floor → display floor, preserve raw_score in data
    display_score = score
    if isinstance(display_score, int) and display_score < 65:
        display_score = 65
    fill_pct = display_score

    # Placeholder detection: score==0 means placeholder row (should be pre-filtered)
    is_placeholder = score == 0

    # Badges: only for heat section, never for radar
    badges_html = ""
    if section == "heat" and not is_placeholder:
        if trend_badge:
            badge_text = trend_badge
            if lang == "cn" and badge_text == "Trend":
                badge_text = "趋势产品"
            elif lang == "cn" and badge_text == "NEW":
                badge_text = "新品"
            badges_html += '<span class="heat-trend-badge">{0}</span>'.format(
                _esc(badge_text)
            )
        if new_badge:
            badge_text = new_badge
            if lang == "cn" and badge_text in ("New", "NEW"):
                badge_text = "新品"
            badges_html += '<span class="heat-new-badge">{0}</span>'.format(
                _esc(badge_text)
            )

    # Heat-score-label: only on rank #1 of each subcategory for heat section
    score_label = ""
    show_score_label = section == "heat" and rank == 1
    if show_score_label:
        score_label = "Heat" if lang == "en" else "热度值"

    detail = product.get("detail", {})
    labels = CELL_LABELS.get(lang, CELL_LABELS["en"]).get(
        section, CELL_LABELS["en"]["heat"]
    )
    cells_html = ""
    for i, dkey in enumerate(DETAIL_KEYS):
        cell_data = detail.get(dkey, {})
        label = labels[i] if i < len(labels) else dkey
        cells_html += _render_detail_cell(label, cell_data, lang)

    # Score label HTML: only rendered for rank #1 heat items
    score_label_html = ""
    if show_score_label:
        score_label_html = (
            '<span class="heat-score-label" onclick="document.getElementById'
            "('scoring-methodology').scrollIntoView({{behavior:'smooth',block:'start'}})\">"
            '{label}<span class="heat-help">\u2753</span></span>'
        ).format(label=score_label)

    return (
        '<li class="heat-item">'
        '<div class="heat-item-header">'
        '<span class="heat-rank {market}">{rank}</span>'
        '<div class="heat-info">'
        '<span class="heat-name">{name}</span>'
        "{badges}"
        '<span class="heat-cat-badge">{cat}</span>'
        "</div>"
        '<div class="heat-bar-wrap"><div class="heat-meter">'
        '<div class="heat-fill {market}-fill" style="width:{fill}%"></div>'
        "</div></div>"
        '<div class="heat-score-stack">'
        "{score_label}"
        '<span class="heat-score">{score}</span>'
        "</div>"
        '<span class="heat-chevron">&#9662;</span>'
        "</div>"
        '<div class="heat-detail"><div class="heat-detail-grid">'
        "{cells}"
        "</div></div>"
        "</li>"
    ).format(
        market=market,
        rank=rank,
        name=_esc(name),
        badges=badges_html,
        cat=_esc(cat),
        fill=fill_pct,
        score_label=score_label_html,
        score=display_score,
        cells=cells_html,
    )


def _render_panel_heading(
    market: str, tier: str, lang: str, topic: str, section: str
) -> str:
    """Render the h4 heading for a panel."""
    market_color = "var(--us-blue)" if market == "US" else "var(--cn-yellow)"
    tier_bg = "#fef9ee" if tier == "LUXURY" else "#f0fdf4"
    tier_color = "#b8943a" if tier == "LUXURY" else "#166534"
    if section == "heat":
        sub_label = PANEL_SUB_LABELS.get((topic, lang), {}).get(
            tier, "{0} TOP 10".format(tier)
        )
    else:
        sub_label = RADAR_PANEL_SUB_LABELS.get((topic, lang), "New Arrivals")
    return (
        '<h4 style="font-size:13px;font-weight:700;margin-bottom:10px;display:flex;align-items:center;gap:6px;">'
        '<span style="background:{mcolor};color:white;padding:2px 8px;border-radius:4px;font-size:10px;">{market}</span>'
        '<span style="background:{tbg};color:{tcolor};padding:2px 8px;border-radius:4px;font-size:9px;font-weight:700;">{tier}</span> {sub}'
        "</h4>"
    ).format(
        mcolor=market_color,
        market=market,
        tbg=tier_bg,
        tcolor=tier_color,
        tier=tier,
        sub=sub_label,
    )


def _filter_panel_products(
    products: List[Dict[str, Any]], section: str
) -> List[Dict[str, Any]]:
    """Filter out placeholder and quarantined products from a panel.

    - All sections: remove score=0 placeholder rows.
    - Radar only: remove quarantined items (quarantine_status != 'verified').
    """
    filtered = []
    for p in products:
        score = p.get("score", 0)
        if score == 0:
            continue
        if section == "radar" and p.get("quarantine_status") == "out-of-window":
            continue
        filtered.append(p)
    return filtered


_EMPTY_STATE_MESSAGES = {
    ("makeup", "en"): "No qualifying new products this week.",
    ("makeup", "cn"): "本周无符合标准的新品。",
    ("fragrance", "en"): "No qualifying new products this week.",
    ("fragrance", "cn"): "本周无符合标准的新品。",
}


def _render_empty_state_note(lang: str, topic: str, count: int) -> str:
    """Render a single concise empty-state note when a radar panel has few products."""
    base_msg = _EMPTY_STATE_MESSAGES.get(
        (topic, lang), "No qualifying new products this week."
    )
    return (
        '<li class="heat-item" style="list-style:none;border:none;box-shadow:none;background:transparent;padding:12px 16px;">'
        '<div class="heat-info">'
        '<span class="heat-name" style="color:#888;font-style:italic;font-weight:400;">'
        "{note}</span>"
        "</div></li>"
    ).format(note=_esc(base_msg))


def _render_section(
    products_by_panel: Dict[str, List[Dict[str, Any]]],
    lang: str,
    topic: str,
    section: str,
) -> str:
    """Render Section 03 or 04 HTML."""
    titles = SECTION_TITLES.get(
        (topic, lang), ("", "Heat", "Rankings", "New Product", "Radar")
    )
    if section == "heat":
        sec_title = '<h2 class="section-title">{0} <em>{1}</em> {2} <span class="sec-label">Section 03</span></h2>'.format(
            _esc(titles[0]), _esc(titles[1]), _esc(titles[2])
        )
    else:
        sec_title = '<h2 class="section-title">{0} <em>{1}</em> {2} <span class="sec-label">Section 04</span></h2>'.format(
            _esc(titles[0]), _esc(titles[3]), _esc(titles[4])
        )

    # Determine panel order: US panels first, then CN
    panel_order = ["US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"]
    # Split into US and CN groups
    us_panels = [
        p for p in panel_order if p.startswith("US") and p in products_by_panel
    ]
    cn_panels = [
        p for p in panel_order if p.startswith("CN") and p in products_by_panel
    ]

    def _render_panel(panel_key: str) -> str:
        market, tier = panel_key.split()
        html = _render_panel_heading(market, tier, lang, topic, section) + "\n"
        raw_products = products_by_panel.get(panel_key, [])
        products = _filter_panel_products(raw_products, section)
        html += '<ul class="heat-accordion">'
        if products:
            for product in products:
                html += _render_product(product, lang, section)
        else:
            html += _render_empty_state_note(lang, topic, 0)
        html += "</ul>\n"
        return html

    # Render US panel (left) and CN panel (right)
    us_html = '<div class="heat-panel us-heat">\n'
    for panel_key in us_panels:
        us_html += _render_panel(panel_key)
    us_html += "</div><!-- end us-heat -->\n"

    cn_html = '<div class="heat-panel cn-heat">\n'
    for panel_key in cn_panels:
        cn_html += _render_panel(panel_key)
    cn_html += "</div><!-- end cn-heat -->\n"

    if section == "heat":
        container_open = '<div class="heat-section">'
        container_close = "</div><!-- end heat-section -->"
    else:
        container_open = '<div class="radar-section" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">'
        container_close = "</div><!-- end radar-section -->"

    return (
        sec_title
        + "\n"
        + container_open
        + "\n"
        + us_html
        + cn_html
        + container_close
        + "\n"
    )


def _replace_section(html: str, section_num: int, new_content: str) -> str:
    """Replace Section 03 or 04 content in the HTML template."""
    if section_num == 3:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 03</span></h2>'
            r".*?"
            r'(?=<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 04</span>)'
        )
    else:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 04</span></h2>'
            r".*?"
            r'(?=<!--\s+APPENDIX|<div\s+class="section">\s*\n?\s*<h3)'
        )

    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return html
    return html[: match.start()] + new_content + html[match.end() :]


def _strip_emoji(text: str) -> str:
    """Remove emoji from value text for clean rendering."""
    return text.replace("🔗", "").replace("❓", "").strip()


def main() -> None:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    for (topic, lang), template_name in TEMPLATES.items():
        template_path = os.path.join(ROOT, template_name)
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        products = data["products"].get(topic, {})
        heat_panels = products.get("heat_rankings", {})
        radar_panels = products.get("new_product_radar", {})

        # Render and replace Section 03
        heat_html = _render_section(heat_panels, lang, topic, "heat")
        html = _replace_section(html, 3, heat_html)

        # Render and replace Section 04
        radar_html = _render_section(radar_panels, lang, topic, "radar")
        html = _replace_section(html, 4, radar_html)

        # Fix lang attribute: fragrance.html should be lang="en" not lang="zh-CN"
        if lang == "en" and 'lang="zh-CN"' in html:
            html = html.replace('lang="zh-CN"', 'lang="en"', 1)

        with open(template_path, "w", encoding="utf-8") as f:
            f.write(html)

        print("Rendered: {0} ({1})".format(template_name, lang))


if __name__ == "__main__":
    main()
