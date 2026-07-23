#!/usr/bin/env python3
"""Deterministic renderer: regenerate the root HTML files from canonical data.

Reads from ``data/months/<target-month>/report.json`` (the canonical monthly
dataset), transformed through the lossless compatibility adapter so that all
downstream rendering logic receives legacy-shaped fields.

The target month is resolved dynamically via ``beauty_weekly.month``:
  1. ``BEAUTY_MONTHLY_MONTH`` env var, or
  2. Most recent ``data/months/<YYYY-MM>/`` with report.json, or
  3. Previous calendar month.

Only replaces Sections 03 (heat rankings) and 04 (new product radar).
All other content (banner, news, trends, appendix, CSS, JS) comes from the
versioned page shells in ``templates/pages`` or, when present, a month-specific
override in ``data/months/<YYYY-MM>/page_shells``. Root HTML files are outputs
only and are never read as runtime templates.

Design invariants
-----------------
* Deterministic: same canonical JSON + same templates = identical HTML output.
* No global split/join mutation.
* One record edit in canonical dataset propagates to all language variants.
* Archives are never touched.
* Idempotent: running twice produces identical output.
"""

import json
import os
import re
import sys
from datetime import date
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.canonical_adapter import canonical_to_legacy  # noqa: E402
from beauty_weekly.month import month_report_path, resolve_month  # noqa: E402

PAGE_SHELL_DIR = os.path.join(ROOT, "templates", "pages")


CANONICAL_PATH = str(month_report_path())
PAGES = {
    ("makeup", "en"): "index.html",
    ("fragrance", "en"): "fragrance.html",
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
}

DETAIL_KEYS = ["price_link", "key_features", "buzz", "brand"]

# Tier display labels per language
TIER_LABELS = {
    "en": {"LUXURY": "LUXURY", "MASSTIGE": "MASSTIGE"},
}

# Section title labels
SECTION_TITLES = {
    ("makeup", "en"): ("Makeup", "Heat", "Rankings", "New Product", "Radar"),
    ("fragrance", "en"): ("Fragrance", "Heat", "Rankings", "New Product", "Radar"),
}

# Panel heading sub-labels
PANEL_SUB_LABELS = {
    ("makeup", "en"): {"LUXURY": "LUXURY TOP 10", "MASSTIGE": "MASSTIGE TOP 10"},
    ("fragrance", "en"): {"LUXURY": "LUXURY TOP 10", "MASSTIGE": "MASSTIGE TOP 10"},
}

# Radar panel heading sub-labels
RADAR_PANEL_SUB_LABELS = {
    ("makeup", "en"): "New Arrivals",
    ("fragrance", "en"): "New Arrivals",
}


def _esc(text: str) -> str:
    """HTML-escape text."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _render_detail_cell(label: str, cell_data: Dict[str, Any], lang: str) -> str:
    """Render a single detail cell div."""
    value = cell_data.get(lang) or cell_data.get("en") or ""
    link_url = cell_data.get("link", "")
    # Clean up value – remove trailing link emoji if we'll render a proper link
    value_clean = value.replace(" 🔗", "").replace("🔗", "").strip()
    link_html = ""
    if link_url:
        link_html = ' <a href="{0}" target="_blank" class="heat-link-icon" title="View product">🔗</a>'.format(
            _esc(link_url),
        )
    trend_tags = cell_data.get("trend_tags", [])
    trend_html = ""
    if trend_tags:
        trend_html = " " + "".join(
            '<span class="heat-trend-tag">{0}</span>'.format(_esc(t)) for t in trend_tags
        )
    return (
        '<div class="heat-detail-cell">'
        '<div class="heat-detail-label">{label}</div>'
        '<div class="heat-detail-value">{trend}{value}{link}</div>'
        "</div>"
    ).format(label=_esc(label), trend=trend_html, value=_esc(value_clean), link=link_html)


def _render_product(product: Dict[str, Any], lang: str, section: str) -> str:
    """Render a single heat-item li element."""
    rank = product["rank"]
    market = product["market"].lower()
    name = product.get("name_en") or product.get("name", "")
    cat = product.get("category_badge", "")
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

    # Trend badges appear in both heat and radar; "new" remains heat-only.
    badges_html = ""
    if not is_placeholder:
        if trend_badge:
            badges_html += '<span class="heat-trend-badge">{0}</span>'.format(_esc(trend_badge))
        if section == "heat" and new_badge:
            badges_html += '<span class="heat-new-badge">{0}</span>'.format(_esc(new_badge))

    # Heat-score-label: only on rank #1 of each subcategory for heat section
    score_label = ""
    show_score_label = section == "heat" and rank == 1
    if show_score_label:
        score_label = "Heat"

    detail = product.get("detail", {})
    labels = CELL_LABELS.get(lang, CELL_LABELS["en"]).get(section, CELL_LABELS["en"]["heat"])
    cells_html = ""
    for i, dkey in enumerate(DETAIL_KEYS):
        cell_data = detail.get(dkey, {})
        label = labels[i] if i < len(labels) else dkey
        cells_html += _render_detail_cell(label, cell_data, lang)

    # Radar trend tag + expandable rationale (Section 04 only)
    radar_trend_html = ""
    if section == "radar" and trend_badge:
        trend_tag_val = product.get("trend_tag") or ""
        trend_rationale_val = product.get("trend_rationale") or ""
        if trend_tag_val:
            radar_trend_html = (
                '<div class="heat-detail" style="padding:8px 16px 4px;">'
                '<span class="heat-trend-tag" style="margin-right:8px;">{tag}</span>'
                '<details style="display:inline;font-size:12px;color:#666;">'
                '<summary style="cursor:pointer;color:#888;">Rationale</summary>'
                '<p style="margin:4px 0 0;color:#555;font-size:12px;line-height:1.5;">{rationale}</p>'
                "</details>"
                "</div>"
            ).format(
                tag=_esc(trend_tag_val),
                rationale=_esc(trend_rationale_val),
            )

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
        "</div>"
        "{radar_trend}"
        "</div>"
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
        radar_trend=radar_trend_html,
    )


def _render_panel_heading(market: str, tier: str, lang: str, topic: str, section: str) -> str:
    """Render the h4 heading for a panel."""
    market_color = "var(--us-blue)" if market == "US" else "var(--cn-yellow)"
    tier_bg = "#fef9ee" if tier == "LUXURY" else "#f0fdf4"
    tier_color = "#b8943a" if tier == "LUXURY" else "#166534"
    if section == "heat":
        sub_label = PANEL_SUB_LABELS.get((topic, lang), {}).get(tier, "{0} TOP 10".format(tier))
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


def _filter_panel_products(products: List[Dict[str, Any]], section: str) -> List[Dict[str, Any]]:
    """Filter out placeholder and quarantined products from a panel.

    - All sections: remove score=0 placeholder rows.
    - Radar only: remove quarantined items (quarantine_status != 'verified').
      No longer require trend_badge for radar panel products.
      Keep existing trend badge/details rendering behavior when the data actually provides it.
    """
    filtered = []
    for p in products:
        score = p.get("score", 0)
        if score == 0:
            continue
        if section == "radar":
            qs = p.get("quarantine_status")
            if qs in ("out-of-window", "unverified"):
                continue
        filtered.append(p)
    return filtered


_EMPTY_STATE_MESSAGES = {
    ("makeup", "en"): "No qualifying new products this month.",
    ("fragrance", "en"): "No qualifying new products this month.",
}

_HEAT_PANEL_NOTE_MESSAGES = {
    "en": "{n} products met this month's signal and evidence thresholds; rankings are not padded.",
}

_HEAT_EMPTY_MESSAGES = {
    "en": "No verified June heat products were available for this panel.",
}


def _render_empty_state_note(lang: str, topic: str, count: int, section: str) -> str:
    """Render a single concise empty-state note when a panel has no qualifying products."""
    if section == "heat":
        base_msg = _HEAT_EMPTY_MESSAGES.get(
            lang,
            "No verified monthly heat products were available for this panel.",
        )
    else:
        base_msg = _EMPTY_STATE_MESSAGES.get(
            (topic, lang), "No qualifying new products this month."
        )
    return (
        '<li class="heat-item" style="list-style:none;border:none;box-shadow:none;background:transparent;padding:12px 16px;">'
        '<div class="heat-info">'
        '<span class="heat-name" style="color:#888;font-style:italic;font-weight:400;">'
        "{note}</span>"
        "</div></li>"
    ).format(note=_esc(base_msg))


def _render_heat_panel_note(lang: str, count: int) -> str:
    """Render a concise note when a heat panel has fewer than 10 products."""
    msg_template = _HEAT_PANEL_NOTE_MESSAGES.get(lang, _HEAT_PANEL_NOTE_MESSAGES["en"])
    msg = msg_template.format(n=count)
    return (
        '<li class="heat-item" style="list-style:none;border:none;box-shadow:none;background:transparent;padding:12px 16px;">'
        '<div class="heat-info">'
        '<span class="heat-name" style="color:#888;font-style:italic;font-weight:400;">'
        "{note}</span>"
        "</div></li>"
    ).format(note=_esc(msg))


def _render_section(
    products_by_panel: Dict[str, List[Dict[str, Any]]],
    lang: str,
    topic: str,
    section: str,
) -> str:
    """Render Section 03 or 04 HTML — US-only panels."""
    titles = SECTION_TITLES.get((topic, lang), ("", "Heat", "Rankings", "New Product", "Radar"))
    if section == "heat":
        sec_title = '<h2 class="section-title">{0} <em>{1}</em> {2} <span class="sec-label">Section 03</span></h2>'.format(
            _esc(titles[0]), _esc(titles[1]), _esc(titles[2])
        )
    else:
        sec_title = '<h2 class="section-title">{0} <em>{1}</em> {2} <span class="sec-label">Section 04</span></h2>'.format(
            _esc(titles[0]), _esc(titles[3]), _esc(titles[4])
        )

    # Four panels: US LUXURY, US MASSTIGE, CN LUXURY, CN MASSTIGE
    all_panels = [
        p
        for p in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")
        if p in products_by_panel
    ]
    us_panels = [p for p in all_panels if p.startswith("US")]
    cn_panels = [p for p in all_panels if p.startswith("CN")]

    def _render_panel(panel_key: str) -> str:
        market, tier = panel_key.split()
        html = _render_panel_heading(market, tier, lang, topic, section) + "\n"
        raw_products = products_by_panel.get(panel_key, [])
        products = _filter_panel_products(raw_products, section)
        html += '<ul class="heat-accordion">'
        if products:
            for product in products:
                html += _render_product(product, lang, section)
            if section == "heat" and len(products) < 10:
                html += _render_heat_panel_note(lang, len(products))
        else:
            html += _render_empty_state_note(lang, topic, len(products), section)
        html += "</ul>\n"
        return html

    # Render US and CN panels
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

    return sec_title + "\n" + container_open + "\n" + us_html + cn_html + container_close + "\n"


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


def _update_banner_month(html: str, month_label: str, date_range: str) -> str:
    """Update the banner and meta tags to reflect the current month.

    Replaces hardcoded 'Month YYYY-MM' references in titles, descriptions,
    and the banner header with the canonical month label and date range.
    """
    source_year, source_month = (int(part) for part in month_label.split("-"))
    issue_date = (
        date(source_year + 1, 1, 1)
        if source_month == 12
        else date(source_year, source_month + 1, 1)
    )
    new_month_str = issue_date.strftime("%B %Y Issue")

    # Update <title>
    html = re.sub(
        r"(<title>[^<]*?)Month\s+\d{4}-\d{2}",
        rf"\g<1>{new_month_str}",
        html,
    )
    # Update meta description
    html = re.sub(
        r'(<meta\s+name="description"\s+content="[^"]*?)Month\s+\d{4}-\d{2}',
        rf"\g<1>{new_month_str}",
        html,
    )
    # Update og:title
    html = re.sub(
        r'(<meta\s+property="og:title"\s+content="[^"]*?)Month\s+\d{4}-\d{2}',
        rf"\g<1>{new_month_str}",
        html,
    )
    # Update og:description
    html = re.sub(
        r'(<meta\s+property="og:description"\s+content="[^"]*?)Month\s+\d{4}-\d{2}',
        rf"\g<1>{new_month_str}",
        html,
    )
    # Update banner h1: "Makeup Industry Monthly · Month YYYY-MM"
    html = re.sub(
        r"(<h1>[^<]*?)Month\s+\d{4}-\d{2}",
        rf"\g<1>{new_month_str}",
        html,
    )
    # Update banner date span (first occurrence after banner)
    html = re.sub(
        r'(<div\s+class="banner-date"><span>)\w+\s+\d+[^<]*(</span>)',
        rf"\g<1>{date_range}\g<2>",
        html,
        count=1,
    )
    # Update version meta tag
    html = re.sub(
        r'(<meta\s+name="version"\s+content=")month\d{4}-\d{2}',
        rf"\g<1>month{month_label}",
        html,
    )
    # Update appendix sources label
    html = re.sub(
        r"(This Month's Sources \(Month\s+)\d{4}-\d{2}",
        rf"\g<1>{month_label}",
        html,
    )
    return html


def _resolve_template_path(month_label: str, output_name: str) -> str:
    month_specific = os.path.join(ROOT, "data", "months", month_label, "page_shells", output_name)
    if os.path.exists(month_specific):
        return month_specific
    return os.path.join(PAGE_SHELL_DIR, output_name)


def _strip_emoji(text: str) -> str:
    """Remove emoji from value text for clean rendering."""
    return text.replace("🔗", "").replace("❓", "").strip()


def main() -> None:
    output_dir = os.environ.get("BEAUTY_WEEKLY_OUTPUT_DIR") or ROOT
    print(f"Rendering from canonical: {CANONICAL_PATH}")
    with open(CANONICAL_PATH, "r", encoding="utf-8") as f:
        canonical = json.load(f)
    data = canonical_to_legacy(canonical)

    month_label = resolve_month()
    date_range = canonical.get("date_range", "")
    monthly_raw = os.path.join(ROOT, "data", "months", month_label, "raw_collected.json")
    monthly_evidence_available = True
    if os.environ.get("BEAUTY_MONTHLY_MONTH") and os.path.exists(monthly_raw):
        with open(monthly_raw, "r", encoding="utf-8") as f:
            monthly_evidence_available = bool(json.load(f).get("articles"))

    for (topic, lang), output_name in PAGES.items():
        template_path = _resolve_template_path(month_label, output_name)
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        products = data["products"].get(topic, {})
        heat_panels = products.get("heat_rankings", {})
        radar_panels = products.get("new_product_radar", {})
        if not monthly_evidence_available:
            panel_names = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")
            heat_panels = {panel: [] for panel in panel_names}
            radar_panels = {panel: [] for panel in panel_names}

        # Render and replace Section 03
        heat_html = _render_section(heat_panels, lang, topic, "heat")
        html = _replace_section(html, 3, heat_html)

        # Render and replace Section 04
        radar_html = _render_section(radar_panels, lang, topic, "radar")
        html = _replace_section(html, 4, radar_html)

        # Update banner to reflect current month (Req 3)
        html = _update_banner_month(html, month_label, date_range)

        # Fix lang attribute: fragrance.html should be lang="en" not lang="zh-CN"
        if lang == "en" and 'lang="zh-CN"' in html:
            html = html.replace('lang="zh-CN"', 'lang="en"', 1)

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_name)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        print("Rendered: {0} ({1})".format(output_name, lang))


if __name__ == "__main__":
    main()
