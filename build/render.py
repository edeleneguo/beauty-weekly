#!/usr/bin/env python3
"""Deterministic renderer: regenerate the root HTML files from canonical data.

Reads from either:
  * ``data/months/<target-month>/report.json`` when month mode is active, or
  * ``data/weeks/<target-week>/report.json`` when week mode is active.

The canonical dataset is transformed through the lossless compatibility
adapter so that all downstream rendering logic receives legacy-shaped fields.

Replaces Section 03 (heat rankings). The former New Product Radar is no
longer rendered; verified launches are identified by a New badge in heat.
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

import html
import calendar
import json
import os
import re
import sys
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.canonical_adapter import canonical_to_legacy  # noqa: E402
from beauty_weekly.month import month_report_path, resolve_month  # noqa: E402
from beauty_weekly.product_taxonomy import (  # noqa: E402
    group_trend_products,
    normalize_report,
)
from beauty_weekly.week import report_path as week_report_path  # noqa: E402
from beauty_weekly.week import resolve_week  # noqa: E402

PAGE_SHELL_DIR = os.path.join(ROOT, "templates", "pages")


MONTH = os.environ.get("BEAUTY_MONTHLY_MONTH")
CANONICAL_PATH = str(month_report_path()) if MONTH else str(week_report_path(resolve_week()))
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
    ("makeup", "en"): {"LUXURY": "TOP 10", "MASSTIGE": "TOP 10"},
    ("fragrance", "en"): {"LUXURY": "TOP 10", "MASSTIGE": "TOP 10"},
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
        trend = product.get("trend") or {}
        trend_tag_val = product.get("trend_tag") or trend.get("tag") or ""
        trend_rationale_val = product.get("trend_rationale") or trend.get("rationale") or ""
        if trend_tag_val:
            radar_trend_html = (
                '<div class="radar-trend-detail" style="padding:0 0 8px;">'
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
        '<div class="heat-detail">'
        "{radar_trend}"
        '<div class="heat-detail-grid">'
        "{cells}"
        "</div>"
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
            launch_evidence = p.get("launch_evidence") or {}
            qs = p.get("quarantine_status") or launch_evidence.get("quarantine_status")
            if qs in ("out-of-window", "unverified"):
                continue
        filtered.append(p)
    return sorted(
        filtered,
        key=lambda p: (
            -float(p.get("score") or 0),
            int(p.get("rank") or 999),
            str(p.get("name") or ""),
        ),
    )


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
    """Render a concise note when a heat panel has fewer than 10 products.

    8-9 carries a yellow coverage warning; fewer is a transparent gap note.
    Rankings are never padded.
    """
    msg_template = _HEAT_PANEL_NOTE_MESSAGES.get(lang, _HEAT_PANEL_NOTE_MESSAGES["en"])
    msg = msg_template.format(n=count)
    if 8 <= count < 10:
        msg = "Coverage warning (yellow): " + msg
        css = "coverage-note coverage-warning"
    else:
        css = "coverage-note coverage-gap"
    return (
        '<li class="heat-item {css}" style="list-style:none;border:none;box-shadow:none;background:transparent;padding:12px 16px;">'
        '<div class="heat-info">'
        '<span class="heat-name" style="color:#888;font-style:italic;font-weight:400;">'
        "{note}</span>"
        "</div></li>"
    ).format(css=css, note=_esc(msg))


def _render_radar_panel_note(lang: str, count: int) -> str:
    """Render a compact transparent coverage note for thin radar panels."""
    msg = (
        "{n} products met this month's signal and evidence thresholds; "
        "transparent coverage warning — rankings are not padded."
    ).format(n=count)
    return (
        '<li class="heat-item coverage-note coverage-gap" style="list-style:none;border:none;box-shadow:none;background:transparent;padding:12px 16px;">'
        '<div class="heat-info">'
        '<span class="heat-name" style="color:#888;font-style:italic;font-weight:400;">'
        "{note}</span>"
        "</div></li>"
    ).format(note=_esc(msg))


def _render_coverage_note(lang: str, section: str, count: int) -> str:
    """Compact per-panel coverage note dispatcher (heat or radar)."""
    if section == "heat":
        return _render_heat_panel_note(lang, count)
    return _render_radar_panel_note(lang, count)


def _coverage_why_text(section: str, entry: Optional[Dict[str, Any]], formal_count: int) -> str:
    """Explain in words why a panel is below its formal target."""
    target = 10 if section == "heat" else 5
    if not entry:
        return (
            "Collection metadata unavailable for this issue; "
            f"{formal_count} formal product(s) verified of {target} target. "
            "Rankings are not padded."
        )
    candidate = int(entry.get("candidate_count", 0))
    verified = int(entry.get("verified_count", 0))
    formal = int(entry.get("formal_included_count", formal_count))
    observation = int(entry.get("observation_count", 0))
    reasons: list[str] = []
    if candidate == 0:
        reasons.append("no candidates were proposed from the collected signal for this panel")
    else:
        quarantined = max(candidate - verified, 0)
        if quarantined:
            reasons.append(
                f"{quarantined} candidate(s) lacked supporting A/B evidence "
                "and were quarantined rather than fabricated"
            )
    if observation:
        reasons.append(
            f"{observation} C-grade signal(s) listed under Market Observation "
            "pending official confirmation"
        )
    if formal < target:
        reasons.append("verified A/B supply below target; collection continues next cycle")
    if not reasons:
        reasons.append("coverage met target")
    return (
        f"Candidates {candidate} · Verified {verified} · Included {formal} "
        f"(target {target}). Why limited: " + "; ".join(reasons) + "."
    )


def _render_collection_status_card(
    lang: str,
    section: str,
    panel_key: str,
    formal_count: int,
    entry: Optional[Dict[str, Any]],
) -> str:
    """Render a visible structured collection-status card inside a thin panel.

    Uses a distinct ``coverage-status-card`` class (never ``heat-item``) so
    formal item validators ignore it.  Counts come only from auditable
    generation metadata — never fabricated.
    """
    del lang
    target = 10 if section == "heat" else 5
    if formal_count >= target and entry and entry.get("status") == "met":
        return ""
    status = (entry or {}).get("status", "below_target")
    why = _coverage_why_text(section, entry, formal_count)
    return (
        '<li class="coverage-status-card" style="list-style:none;border:1px dashed #d1d5db;border-radius:8px;background:#fafafa;padding:12px 16px;">'
        '<div class="heat-info">'
        '<span class="heat-name" style="font-weight:700;">'
        "Collection status — {panel}: {formal}/{target} formally included ({status})"
        "</span>"
        "</div>"
        '<div class="coverage-why" style="font-size:12px;color:#555;margin-top:4px;">'
        "{why}</div>"
        "</li>"
    ).format(
        panel=_esc(panel_key),
        formal=formal_count,
        target=target,
        status=_esc(str(status)),
        why=_esc(why),
    )


def _render_market_observation(topic: str, lang: str, observations_by_panel: dict) -> str:
    """Render the market observation candidate area.

    C-grade social/KOL signals only, labeled pending official confirmation
    and never mixed into the formal ranking/radar lists.  Uses a distinct
    ``observation-item`` class so formal panel/item validators ignore it.
    """
    panels = [(panel, items) for panel, items in (observations_by_panel or {}).items() if items]
    if not panels:
        return ""
    items_html = ""
    for panel, items in sorted(panels):
        for product in items:
            name = product.get("name_en") or product.get("name", "")
            launch_ev = product.get("launch_evidence") or {}
            grade = launch_ev.get("evidence_grade") or product.get("evidence_grade") or "C"
            launch_date = launch_ev.get("launch_date") or product.get("launch_date") or ""
            ev = launch_ev.get("evidence") or {}
            ev_url = ev.get("url") or product.get("evidence_url") or ""
            ev_type = ev.get("type") or product.get("evidence_type") or "social_media"
            label = product.get("observation_status") or "pending official confirmation"
            date_text = launch_date or "date unavailable"
            source_html = ""
            if ev_url:
                source_html = (
                    ' <a href="{0}" target="_blank" class="heat-link-icon" '
                    'title="View source">🔗</a>'
                ).format(_esc(str(ev_url)))
            items_html += (
                '<li class="observation-item">'
                '<div class="heat-info">'
                '<span class="heat-name">{name}</span>'
                '<span class="heat-cat-badge">Grade {grade} · {date}</span>'
                '<span class="observation-label">{label}</span>'
                "</div>"
                '<div class="observation-meta">Source: {evtype}{source}</div>'
                "</li>"
            ).format(
                name=_esc(str(name)),
                grade=_esc(str(grade)),
                date=_esc(str(date_text)),
                label=_esc(str(label)),
                evtype=_esc(str(ev_type)),
                source=source_html,
            )
    return (
        '<div class="market-observation">'
        '<h3 class="observation-heading">Market Observation — Pending Official Confirmation</h3>'
        '<p class="observation-sub">Social/KOL signals awaiting official confirmation; '
        "not part of the formal ranking.</p>"
        '<ul class="observation-list">{items}</ul>'
        "</div>"
    ).format(items=items_html)


def _render_section(
    products_by_panel: Dict[str, List[Dict[str, Any]]],
    lang: str,
    topic: str,
    section: str,
    coverage_by_panel: Optional[Dict[str, Dict[str, Any]]] = None,
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
        entry = (coverage_by_panel or {}).get(panel_key)
        html += '<ul class="heat-accordion">'
        if products:
            for product in products:
                html += _render_product(product, lang, section)
            if section == "heat" and len(products) < 10:
                html += _render_coverage_note(lang, section, len(products))
            if section == "radar" and 1 <= len(products) < 5:
                html += _render_coverage_note(lang, section, len(products))
        else:
            html += _render_empty_state_note(lang, topic, len(products), section)
        needs_card = (section == "heat" and len(products) < 10) or (
            section == "radar" and len(products) < 5
        )
        if needs_card:
            html += _render_collection_status_card(lang, section, panel_key, len(products), entry)
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
    if section_num == 1:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 01</span></h2>'
            r".*?"
            r'(?=<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 02</span>)'
        )
    elif section_num == 2:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 02</span></h2>'
            r".*?"
            r'(?=<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 03</span>)'
        )
    elif section_num == 3:
        pattern = (
            r'<h2\s+class="section-title">[^<]*<em>[^<]*</em>[^<]*'
            r'<span\s+class="sec-label">Section 03</span></h2>'
            r".*?"
            r'(?=<!--\s+APPENDIX|<div\s+class="section">\s*\n?\s*<h3)'
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


TOPIC_TERMS = {
    "makeup": (
        "makeup", "lipstick", "lip gloss", "foundation", "concealer", "blush",
        "mascara", "eyeshadow", "eyeliner", "brow", "primer", "cosmetic",
    ),
    "fragrance": (
        "fragrance", "perfume", "parfum", "scent", "cologne", "eau de", "musk",
        "gourmand", "oud", "floral",
    ),
}


TREND_CONTENT = {
    "makeup": {
        "Skincare Foundation": {
            "summary": "Base makeup is moving toward serum textures, hydration and visible skin benefits.",
            "description": (
                "Foundation, cushion and skin-tint launches increasingly combine complexion correction "
                "with skincare language such as serum, hydration and barrier support. The opportunity is "
                "not simply adding an ingredient claim: the finish, wear and shade range still need to "
                "perform like makeup."
            ),
            "keywords": ("serum foundation", "skin tint", "skincare foundation", "hybrid beauty", "complexion", "foundation"),
            "action_direction": "Serum foundation + luminous cushion platform",
            "action": (
                "Prioritize a light serum foundation and refillable cushion with credible hydration testing, "
                "skin-like coverage and a shade architecture that can travel across CN and US."
            ),
        },
        "Functional Lip": {
            "summary": "Hydration, shine and long wear are converging in hybrid lip formats.",
            "description": (
                "The strongest lip direction combines an immediate sensorial payoff with a care benefit: "
                "glass-like shine, blurred color or stain performance without a dry after-feel. Balm, gloss, "
                "lipstick and lip mud are becoming a connected format system rather than separate categories."
            ),
            "keywords": ("lip stain", "lipstick", "lip gloss", "lip balm", "lip care", "lip color", "lip treatment", "lip blushing"),
            "action_direction": "High-shine treatment gloss + airy matte lip mud",
            "action": (
                "Develop two complementary textures: a high-shine treatment gloss for hydration and volume, "
                "and an airy matte lip mud that preserves comfort and even fade. Validate wear, transfer and "
                "after-feel separately in CN and US."
            ),
        },
        "Low-Saturation Pastel": {
            "summary": "Soft-focus, muted color is replacing harder contrast across cheeks, lips and eyes.",
            "description": (
                "Low-saturation color is appearing through diffused blush, softly blurred lips and restrained "
                "eye accents. The commercial expression is less about a single seasonal shade and more about "
                "buildable payoff, soft-focus texture and wearable color families."
            ),
            "keywords": ("pastel", "soft glam", "anti-blush", "blush", "silver eyeliner", "muted", "soft blur"),
            "action_direction": "Muted cheek-and-lip color wardrobe",
            "action": (
                "Build a coordinated muted palette around cream-to-powder blush, sheer cheek tint and blurred "
                "lip color. Test shade readability on multiple skin tones before committing to a seasonal set."
            ),
        },
    },
    "fragrance": {
        "Milky Musk": {
            "summary": "Soft musk is becoming creamier, closer to skin and easier to layer.",
            "description": (
                "Milky and skin-musk structures are shifting gourmand fragrance toward softer, intimate wear. "
                "Texture, comfort and layering matter as much as sweetness, creating room for lighter formats "
                "and personal-scent positioning."
            ),
            "keywords": ("milky", "milk", "musk", "lactonic", "skin scent"),
            "action_direction": "Layerable milky-musk wardrobe",
            "action": "Explore a close-to-skin musk with a restrained lactonic accord, plus a lighter mist or hair-perfume companion.",
        },
        "Matcha Fragrance": {
            "summary": "Tea accords are expanding beyond freshness into creamy and gourmand territory.",
            "description": (
                "Matcha and tea notes provide a recognizable bridge between green freshness and gourmand "
                "comfort. The strongest concepts balance bitterness, steamed milk or soft woods rather than "
                "relying on novelty alone."
            ),
            "keywords": ("matcha", "green tea", "black tea", "tea fragrance"),
            "action_direction": "Matcha tea scent with controlled sweetness",
            "action": "Prototype a matcha accord in both airy-green and creamy-gourmand directions, then validate longevity and cultural readability.",
        },
        "Rose Revival": {
            "summary": "Rose is returning through fresher petals, modern woods and less traditional sweetness.",
            "description": (
                "Current rose launches treat the note as a flexible texture rather than a fixed floral code, "
                "moving between translucent petals, fruit, clean musk and darker woody contrasts."
            ),
            "keywords": ("rose fragrance", "rose perfume", "rose petal", "rose scent"),
            "action_direction": "Modern rose texture study",
            "action": "Develop one translucent petal-musk route and one deeper rose-wood route; test which carries stronger newness without losing recognition.",
        },
        "Oriental Narrative": {
            "summary": "Resin, oud and incense are being reframed through clearer stories and modern formats.",
            "description": (
                "Oud, incense and woods remain relevant when the storytelling is specific and the structure "
                "avoids generic heaviness. Extrait, hair perfume and focused collections can make the direction "
                "more accessible to distinct occasions and price points."
            ),
            "keywords": ("oud", "incense", "sandalwood", "resin", "oriental fragrance", "extrait"),
            "action_direction": "Story-led resin and wood collection",
            "action": "Choose a precise cultural and olfactive narrative first, then build an eau de parfum and lighter extension around the same signature accord.",
        },
    },
}


SIGNAL_SOURCE_RULES = (
    (("小红书", "xiaohongshu"), "Xiaohongshu"),
    (("抖音", "douyin"), "Douyin"),
    (("tiktok",), "TikTok"),
    (("sephora",), "Sephora"),
    (("instagram",), "Instagram"),
    (("circana",), "Circana"),
    (("wgsn",), "WGSN"),
    (("beautymatter", "beauty matter"), "BeautyMatter"),
    (("ulta",), "Ulta"),
    (("pinterest",), "Pinterest"),
)


def _signal_source(article: Dict[str, Any]) -> str:
    blob = " ".join(
        str(article.get(field) or "") for field in ("source", "title", "url")
    ).casefold()
    for cues, label in SIGNAL_SOURCE_RULES:
        if any(cue in blob for cue in cues):
            return label
    return _publisher_label(article)


def _signal_type(article: Dict[str, Any]) -> str:
    blob = " ".join(
        str(article.get(field) or "")
        for field in ("source", "title", "summary", "reference_type")
    ).casefold()
    if any(cue in blob for cue in ("social", "tiktok", "douyin", "抖音", "小红书", "influencer")):
        return "Social signal"
    if any(cue in blob for cue in ("sales", "retail", "e-commerce", "ecommerce", "pos ", "bestseller")):
        return "Sales / retail"
    if any(cue in blob for cue in ("forecast", "prediction", "trend forecasting", "wgsn")):
        return "Forecast"
    return "Review / media"


def _signal_value(article: Dict[str, Any]) -> str:
    blob = _plain_text(f"{article.get('title', '')} {article.get('summary', '')}")
    patterns = (
        r"[+−-]?\d[\d,.]*\s*%",
        r"[$¥£€]\s*\d[\d,.]*(?:\s*(?:billion|million|bn|m))?",
        r"\d[\d,.]*\+?\s*(?:reviews?|million|billion|万|亿)",
        r"(?:Top|TOP)\s*\d+",
    )
    for pattern in patterns:
        match = re.search(pattern, blob, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return {
        "Sales / retail": "Retail",
        "Social signal": "Social",
        "Forecast": "Forecast",
        "Review / media": "Review",
    }[_signal_type(article)]


def _trend_supporting_articles(
    articles: List[Dict[str, Any]], topic: str, trend_name: str, month_label: str
) -> List[Dict[str, Any]]:
    content = TREND_CONTENT[topic][trend_name]
    ranked: List[tuple[int, str, Dict[str, Any]]] = []
    for article in articles:
        if not _in_month(article, month_label):
            continue
        blob = _plain_text(
            f"{article.get('title', '')} {article.get('summary', '')} {article.get('source', '')}"
        ).casefold()
        keyword_hits = 0
        for keyword in content["keywords"]:
            if re.search(r"[^\x00-\x7f]", keyword) or " " in keyword:
                matched = keyword in blob
            else:
                matched = bool(
                    re.search(
                        rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])",
                        blob,
                    )
                )
            keyword_hits += int(matched)
        if not keyword_hits:
            continue
        source = _signal_source(article)
        platform_bonus = 3 if source in {label for _, label in SIGNAL_SOURCE_RULES} else 0
        metric_bonus = 2 if _signal_value(article) not in {"Retail", "Social", "Forecast", "Review"} else 0
        ranked.append((keyword_hits * 10 + platform_bonus + metric_bonus, source, article))
    ranked.sort(key=lambda item: (item[0], str(item[2].get("date") or "")), reverse=True)

    selected: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    source_counts: Dict[str, int] = {}
    for _, source, article in ranked:
        url = str(article.get("url") or "")
        if not url or url in seen_urls or source_counts.get(source, 0) >= 1:
            continue
        selected.append(article)
        seen_urls.add(url)
        source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) == 4:
            break
    return selected


def _in_month(article: Dict[str, Any], month_label: str) -> bool:
    try:
        parsed = parsedate_to_datetime(str(article.get("date", "")))
        return parsed.strftime("%Y-%m") == month_label
    except (TypeError, ValueError, OverflowError):
        return False


def _plain_text(value: Any) -> str:
    decoded = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", decoded)).strip()


def _topic_articles(raw: Dict[str, Any], topic: str, month_label: str) -> List[Dict[str, Any]]:
    terms = TOPIC_TERMS[topic]
    other_terms = TOPIC_TERMS["fragrance" if topic == "makeup" else "makeup"]
    selected = []
    seen = set()
    for article in raw.get("articles", []):
        if not _in_month(article, month_label):
            continue
        haystack = _plain_text(f"{article.get('title', '')} {article.get('summary', '')}").lower()
        score = sum(term in haystack for term in terms)
        other_score = sum(term in haystack for term in other_terms)
        url = str(article.get("url", "")).strip()
        title = _plain_text(article.get("title"))
        if not title or not url or score == 0 or score < other_score or url in seen:
            continue
        seen.add(url)
        selected.append((score, article))
    selected.sort(key=lambda item: (item[0], str(item[1].get("date", ""))), reverse=True)
    return [article for _, article in selected[:8]]


PUBLISHER_LABELS = {
    "bustle.com": "Bustle",
    "cosmopolitan.com": "Cosmopolitan",
    "cj.sina.com.cn": "Sina Finance",
    "finance.yahoo.com": "Yahoo Finance",
    "glam.com": "Glam",
    "harpersbazaar.com": "Harper's Bazaar",
    "hypebae.com": "Hypebae",
    "instyle.com": "InStyle",
    "nstperfume.com": "Now Smell This",
    "prnewswire.com": "PR Newswire",
    "refinery29.com": "Refinery29",
    "vogue.com.tw": "Vogue Taiwan",
    "whowhatwear.com": "Who What Wear",
}


def _publisher_label(article: Dict[str, Any]) -> str:
    host = urlparse(str(article.get("url") or "")).netloc.casefold().removeprefix("www.")
    if host in PUBLISHER_LABELS:
        return PUBLISHER_LABELS[host]
    root = host.split(".")[0].replace("-", " ").strip()
    return root.title() if root else "Verified source"


def _news_type(article: Dict[str, Any]) -> tuple[str, str]:
    text = _plain_text(
        f"{article.get('title', '')} {article.get('reference_type', '')}"
    ).casefold()
    if any(cue in text for cue in ("regulation", "regulatory", "compliance", "ban ")):
        return "reg", "Regulatory"
    if any(cue in text for cue in ("acquisition", "acquires", "funding", "investment", "merger")):
        return "ma", "M&A"
    if any(
        cue in text
        for cue in (" launches ", " launched ", "introduces", " debuts ", " unveils ", "releases")
    ):
        return "event", "Launch"
    if any(cue in text for cue in ("report", "sales", "growth", "survey", "data", "market size")):
        return "data", "Data"
    return "market", "Market"


def _render_news(topic: str, articles: List[Dict[str, Any]], date_range: str) -> str:
    label = "Makeup Industry" if topic == "makeup" else "Fragrance Industry"
    cards = []
    for article in articles:
        market = str(article.get("market", "GLOBAL")).upper()
        region = "cn" if market == "CN" else ("us" if market == "US" else "global")
        summary = _plain_text(article.get("summary")) or "Verified source item for this reporting period."
        tag_class, tag_label = _news_type(article)
        cards.append(
            '<div class="news-card"><div class="news-card-header">'
            f'<span class="news-region-tag {region}">{_esc(market)}</span>'
            f'<span class="news-card-title"><a href="{_esc(str(article.get("url", "")))}" target="_blank">{_esc(_plain_text(article.get("title")))}</a></span>'
            f'<span class="news-card-tag {tag_class}">{tag_label}</span>'
            '<span class="news-card-chevron">&#9662;</span></div>'
            f'<div class="news-card-brief">{_esc(summary[:240])}</div>'
            f'<div class="news-card-body"><div class="news-card-body-inner">Source: {_esc(_publisher_label(article))} · {_esc(str(article.get("date", "")))}</div></div></div>'
        )
    if not cards:
        cards.append(f'<div class="collection-status-card">No verified {topic} news was found for { _esc(date_range) }. Coverage is flagged for source backfill.</div>')
    return (
        f'<h2 class="section-title">{label} <em>News</em> <span class="sec-label">Section 01</span></h2>\n'
        f'<div class="news-grid">{"".join(cards)}</div>\n'
    )


def _group_trend_products(
    topic: str, products: Dict[str, Any]
) -> Dict[str, List[tuple[str, Dict[str, Any]]]]:
    return group_trend_products(topic, products)


def _render_trends(
    topic: str,
    products: Dict[str, Any],
    date_range: str,
    articles: Optional[List[Dict[str, Any]]] = None,
    month_label: str = "",
) -> str:
    label = "Makeup" if topic == "makeup" else "Fragrance"
    groups = _group_trend_products(topic, products)
    ranked = sorted(
        ((name, rows) for name, rows in groups.items() if rows),
        key=lambda item: len(item[1]), reverse=True,
    )[:4]
    cards = []
    for trend_name, rows in ranked:
        content = TREND_CONTENT[topic][trend_name]
        markets = sorted({panel.split()[0] for panel, _ in rows})
        market_tags = "".join(
            f'<span class="region-tag {market.casefold()}">{market}</span>' for market in markets
        )
        strength = (
            "Cross-market"
            if len(rows) >= 4 and len(markets) > 1
            else ("Supported" if len(rows) >= 2 else "Emerging")
        )
        strength_class = "strong" if strength == "Cross-market" else "mid"
        signal_chips = ""
        supporting = _trend_supporting_articles(
            articles or [], topic, trend_name, month_label
        )
        for index, article in enumerate(supporting, 1):
            market = str(article.get("market") or "GLOBAL").upper()
            chip_market = market.casefold() if market in {"CN", "US"} else "global"
            source = _signal_source(article)
            signal_type = _signal_type(article)
            title = _plain_text(article.get("title"))
            if re.search(r"[\u3400-\u9fff]", title):
                title = f"{source} coverage supporting {trend_name}"
            if len(title) > 74:
                title = title[:71].rstrip() + "..."
            signal_chips += (
                f'<a class="signal-chip chip-{chip_market} chip-{index}" '
                f'href="{_esc(str(article.get("url") or ""))}" target="_blank">'
                f'<div class="chip-desc">{_esc(source)}</div>'
                f'<div class="chip-num">{_esc(_signal_value(article))}</div>'
                f'<div class="chip-sub">{_esc(title)}</div>'
                f'<div class="chip-tag">{_esc(signal_type)}</div></a>'
            )
        if not signal_chips:
            signal_chips = (
                '<div class="collection-status-card">No channel-level supporting data '
                'met this month\'s source threshold; the trend remains directional.</div>'
            )
        cards.append(
            '<div class="trend-v-card"><div class="trend-v-header">'
            f'<h4><span class="heat-trend-tag">{_esc(trend_name)}</span> · {_esc(content["summary"])} {market_tags}</h4>'
            f'<span class="dec-strength-tag {strength_class}">{strength}</span>'
            '<span class="trend-v-arrow">▼</span></div>'
            '<div class="trend-v-body">'
            f'<div class="driver-summary">{_esc(content["description"])}</div>'
            '<div style="font-size:10px;font-weight:800;color:#6b7280;text-transform:uppercase;'
            'letter-spacing:0;margin:14px 0 8px;">Supporting data</div>'
            f'<div class="signal-strip">{signal_chips}</div>'
            '<div class="action-block"><div class="act-header">'
            '<span class="act-label">NPD Action</span>'
            f'<span class="act-direction">{_esc(content["action_direction"])}</span>'
            f'<span class="dec-strength-tag {strength_class}">{strength}</span></div>'
            f'<div class="act-detail-text">{_esc(content["action"])}</div></div>'
            '</div></div>'
        )
    if not cards:
        cards.append(f'<div class="collection-status-card">No verified {topic} trend signals were available for {_esc(date_range)}. Coverage is flagged for source backfill.</div>')
    return (
        f'<h2 class="section-title">{label} <em>Trend</em> Report <span class="sec-label">Section 02</span></h2>\n'
        f'<div class="common-trends-section">{"".join(cards)}</div>\n'
    )


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


def _update_next_update(html: str, month_label: str) -> str:
    """Set the footer to the issue after the one represented by month_label."""
    source_year, source_month = (int(part) for part in month_label.split("-"))
    next_month = source_month + 2
    next_year = source_year
    while next_month > 12:
        next_month -= 12
        next_year += 1
    next_label = f"{calendar.month_name[next_month]} {next_year}"
    return re.sub(
        r"Next update:\s*[A-Za-z]+\s+\d{4}",
        f"Next update: {next_label}",
        html,
    )


def _resolve_template_path(month_label: str, output_name: str) -> str:
    if os.environ.get("BEAUTY_USE_CURRENT_TEMPLATE") == "1":
        return os.path.join(PAGE_SHELL_DIR, output_name)
    month_specific = os.path.join(ROOT, "data", "months", month_label, "page_shells", output_name)
    if os.path.exists(month_specific):
        return month_specific
    return os.path.join(PAGE_SHELL_DIR, output_name)


def _strip_emoji(text: str) -> str:
    """Remove emoji from value text for clean rendering."""
    return text.replace("🔗", "").replace("❓", "").strip()


def _remove_legacy_radar_copy(html_text: str) -> str:
    """Remove obsolete Radar explanations from historical page shells."""
    return re.sub(
        r'<p\b[^>]*>(?:(?!</p>).)*(?:New Product Radar|Section 04)(?:(?!</p>).)*</p>\s*',
        "",
        html_text,
        flags=re.DOTALL | re.IGNORECASE,
    )


def main() -> None:
    output_dir = os.environ.get("BEAUTY_WEEKLY_OUTPUT_DIR") or ROOT
    print(f"Rendering from canonical: {CANONICAL_PATH}")
    with open(CANONICAL_PATH, "r", encoding="utf-8") as f:
        canonical = json.load(f)
    canonical = normalize_report(canonical)
    data = canonical_to_legacy(canonical)

    month_label = resolve_month()
    date_range = canonical.get("date_range", "")
    monthly_raw = os.path.join(ROOT, "data", "months", month_label, "raw_collected.json")
    monthly_evidence_available = True
    raw_collection: Dict[str, Any] = {"articles": [], "trends": []}
    if os.environ.get("BEAUTY_MONTHLY_MONTH") and os.path.exists(monthly_raw):
        with open(monthly_raw, "r", encoding="utf-8") as f:
            raw_collection = json.load(f)
            monthly_evidence_available = bool(raw_collection.get("articles"))

    for (topic, lang), output_name in PAGES.items():
        template_path = _resolve_template_path(month_label, output_name)
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        products = data["products"].get(topic, {})
        heat_panels = products.get("heat_rankings", {})
        if not monthly_evidence_available:
            panel_names = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")
            heat_panels = {panel: [] for panel in panel_names}

        topic_coverage = (data.get("panel_coverage") or {}).get(topic, {})
        # Render current-month editorial sections. These must never inherit a
        # prior month's static content from the page shell.
        news_html = _render_news(topic, _topic_articles(raw_collection, topic, month_label), date_range)
        html = _replace_section(html, 1, news_html)
        trends_html = _render_trends(
            topic,
            products,
            date_range,
            raw_collection.get("articles", []),
            month_label,
        )
        html = _replace_section(html, 2, trends_html)

        # Render and replace Section 03
        heat_html = _render_section(
            heat_panels, lang, topic, "heat", topic_coverage.get("heat_rankings")
        )
        html = _replace_section(html, 3, heat_html)
        html = _remove_legacy_radar_copy(html)

        # Update banner to reflect current month (Req 3)
        html = _update_banner_month(html, month_label, date_range)
        html = _update_next_update(html, month_label)

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
