#!/usr/bin/env python3
"""Deterministic renderer: regenerate the root HTML files from canonical data.

Reads from either:
  * ``data/months/<target-month>/report.json`` when month mode is active, or
  * ``data/weeks/<target-week>/report.json`` when week mode is active.

The canonical dataset is transformed through the lossless compatibility
adapter so that all downstream rendering logic receives legacy-shaped fields.

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

import html
import json
import os
import re
import sys
import unicodedata
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.canonical_adapter import canonical_to_legacy  # noqa: E402
from beauty_weekly.month import month_report_path, resolve_month  # noqa: E402
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


def _render_score_breakdown(product: Dict[str, Any]) -> str:
    """Render weighted score explainability and data coverage."""
    breakdown = product.get("score_breakdown") or {}
    components = breakdown.get("components") or []
    if not components:
        return ""

    component_html = ""
    for component in components:
        label = str(component.get("label") or "")
        points = int(component.get("points") or 0)
        max_points = int(component.get("max_points") or 0)
        weight_pct = round(float(component.get("weight") or 0) * 100)
        component_html += (
            '<span style="display:inline-flex;align-items:center;gap:4px;'
            "padding:3px 8px;border:1px solid #e5e7eb;border-radius:4px;"
            'background:#fff;margin:0 6px 6px 0;font-size:11px;color:#374151;">'
            "<span>{label}</span>"
            '<strong style="color:#111827;">{points}/{max_points}</strong>'
            '<span style="color:#6b7280;">{weight_pct}%</span>'
            "</span>"
        ).format(
            label=_esc(label),
            points=points,
            max_points=max_points,
            weight_pct=weight_pct,
        )

    data_quality = product.get("data_quality") or {}
    coverage_score = data_quality.get("coverage_score")
    link_type = str(data_quality.get("link_type") or "unknown").replace("_", " ")
    source_type = str(data_quality.get("source_type") or "unknown").replace("_", " ")
    missing = data_quality.get("missing_fields") or []
    missing_text = ", ".join(str(field).replace("_", " ") for field in missing) or "none"
    quality_line = (
        "Data coverage {coverage}/100 · Link: {link_type} · Source: {source_type} · "
        "Missing: {missing}"
    ).format(
        coverage=coverage_score if coverage_score is not None else "n/a",
        link_type=link_type,
        source_type=source_type,
        missing=missing_text,
    )

    status = (
        "Display allocation only; raw recompute awaits normalized sales/social/review/trend series."
    )
    return (
        '<div class="heat-detail-cell full-width">'
        '<div class="heat-detail-label">Score Breakdown</div>'
        '<div class="heat-detail-value">{components}</div>'
        '<div style="font-size:11px;color:#6b7280;line-height:1.45;margin-top:2px;">{quality}</div>'
        '<div style="font-size:11px;color:#9ca3af;line-height:1.45;margin-top:2px;">{status}</div>'
        "</div>"
    ).format(
        components=component_html,
        quality=_esc(quality_line),
        status=_esc(status),
    )


def _render_launch_evidence(product: Dict[str, Any], section: str) -> str:
    if section != "radar":
        return ""
    launch_evidence = product.get("launch_evidence") or {}
    grade = launch_evidence.get("evidence_grade") or product.get("evidence_grade")
    date_basis = str(launch_evidence.get("date_basis") or product.get("date_basis") or "").replace(
        "_", " "
    )
    launch_date = launch_evidence.get("launch_date") or product.get("launch_date")
    if not grade and not launch_date:
        return ""
    value = f"Grade {grade or 'n/a'} · {launch_date or 'date unavailable'}"
    if date_basis:
        value += f" · {date_basis}"
    return (
        '<div class="heat-detail-cell full-width">'
        '<div class="heat-detail-label">Launch Evidence</div>'
        '<div class="heat-detail-value">{value}</div>'
        "</div>"
    ).format(value=_esc(value))


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
    cells_html += _render_launch_evidence(product, section)
    cells_html += _render_score_breakdown(product)

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


def _render_news(topic: str, articles: List[Dict[str, Any]], date_range: str) -> str:
    label = "Makeup Industry" if topic == "makeup" else "Fragrance Industry"
    cards = []
    for article in articles:
        market = str(article.get("market", "GLOBAL")).upper()
        region = "cn" if market == "CN" else ("us" if market == "US" else "global")
        summary = _plain_text(article.get("summary")) or "Verified source item for this reporting period."
        cards.append(
            '<div class="news-card"><div class="news-card-header">'
            f'<span class="news-region-tag {region}">{_esc(market)}</span>'
            f'<span class="news-card-title"><a href="{_esc(str(article.get("url", "")))}" target="_blank">{_esc(_plain_text(article.get("title")))}</a></span>'
            '<span class="news-card-chevron">&#9662;</span></div>'
            f'<div class="news-card-brief">{_esc(summary[:240])}</div>'
            f'<div class="news-card-body"><div class="news-card-body-inner">Source: {_esc(str(article.get("source", "verified source")))} · {_esc(str(article.get("date", "")))}</div></div></div>'
        )
    if not cards:
        cards.append(f'<div class="collection-status-card">No verified {topic} news was found for { _esc(date_range) }. Coverage is flagged for source backfill.</div>')
    return (
        f'<h2 class="section-title">{label} <em>News</em> <span class="sec-label">Section 01</span></h2>\n'
        f'<div class="news-grid">{"".join(cards)}</div>\n'
    )


TREND_TAXONOMY = {
    "makeup": ("Skincare Foundation", "Functional Lip", "Low-Saturation Pastel"),
    "fragrance": (
        "Milky Musk",
        "Matcha Fragrance",
        "Rose Revival",
        "Oriental Narrative",
    ),
}


def _normalized_product_aliases(product: Dict[str, Any]) -> set[str]:
    aliases = set()
    for field in ("name", "name_cn"):
        value = str(product.get(field, "")).casefold()
        normalized = "".join(char for char in value if char.isalnum())
        if normalized:
            aliases.add(normalized)
    return aliases


def _trend_identity_keys(product: Dict[str, Any]) -> set[str]:
    """Return stable keys used only to avoid duplicate trend signals.

    A product can enter the report through more than one source or with an
    English and localized title.  Name aliases cover the common case; the
    source/brand/category key covers localized titles that still point to the
    same evidence page without merging unrelated products from a roundup.
    """
    keys = {f"name:{alias}" for alias in _normalized_product_aliases(product)}
    detail = product.get("detail") or {}
    source_url = str((detail.get("price_link") or {}).get("link") or "").strip().casefold()
    name = unicodedata.normalize("NFKD", str(product.get("name") or ""))
    ascii_name = name.encode("ascii", "ignore").decode("ascii")
    brand_match = re.match(r"\s*([a-z0-9][a-z0-9'&.-]{2,})", ascii_name.casefold())
    category = re.sub(
        r"[^a-z0-9]+",
        "",
        unicodedata.normalize("NFKD", str(product.get("category_badge") or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold(),
    )
    if source_url and brand_match and category:
        keys.add(f"source:{source_url}|brand:{brand_match.group(1)}|category:{category}")
    return keys


def _explicit_trend_tag(product: Dict[str, Any]) -> str:
    trend = product.get("trend") or {}
    return str(product.get("trend_badge") or trend.get("tag") or "").strip()


def _matches_trend(topic: str, trend_name: str, product: Dict[str, Any]) -> bool:
    if _explicit_trend_tag(product) == trend_name:
        return True

    detail = product.get("detail") or {}
    name = _plain_text(f"{product.get('name', '')} {product.get('name_cn', '')}").casefold()
    category = _plain_text(product.get("category_badge", "")).casefold()
    features = _plain_text(str((detail.get("key_features") or {}).get("en", ""))).casefold()
    descriptive = _plain_text(
        " ".join(
            str((detail.get(field) or {}).get("en", ""))
            for field in ("key_features", "buzz", "brand")
        )
    ).casefold()
    full_text = f"{name} {category} {descriptive}"

    if topic == "makeup":
        if trend_name == "Skincare Foundation":
            complexion = any(
                cue in category
                for cue in ("foundation", "cushion", "skin tint", "primer", "complexion")
            )
            care = any(
                cue in full_text
                for cue in (
                    "serum",
                    "skincare",
                    "skin care",
                    "hydrating",
                    "moistur",
                    "nourish",
                    "treatment",
                    "peptide",
                    "niacinamide",
                    "ceramide",
                    "hyaluronic",
                    "养肤",
                )
            )
            return complexion and care
        if trend_name == "Functional Lip":
            lip_product = "lip" in category or any(
                cue in name for cue in ("lip", "唇膏", "唇釉", "润唇", "唇霜")
            )
            benefit = any(
                cue in full_text
                for cue in (
                    "balm",
                    "treatment",
                    "hydrating",
                    "moistur",
                    "peptide",
                    "serum",
                    "repair",
                    "nourish",
                    "comfort",
                    "plump",
                    "volumiz",
                    "润唇",
                    "保湿",
                    "修护",
                )
            )
            return lip_product and benefit
        if trend_name == "Low-Saturation Pastel":
            return any(
                cue in full_text
                for cue in (
                    "low-saturation",
                    "low saturation",
                    "pastel",
                    "muted",
                    "macaron",
                    "lilac",
                    "lavender",
                    "powder blue",
                    "pale pink",
                    "马卡龙",
                    "馬卡龍",
                    "低饱和",
                    "低飽和",
                )
            )

    if trend_name == "Milky Musk":
        return any(
            cue in full_text
            for cue in (
                "milky",
                "milk accord",
                "lactonic",
                "mochi milk",
                "skin scent",
                "white musk",
                "soft musk",
                "cashmere musk",
                "乳感",
                "白麝香",
            )
        )
    if trend_name == "Matcha Fragrance":
        return "matcha" in full_text or "抹茶" in full_text
    if trend_name == "Rose Revival":
        return "rose" in features or any(
            cue in name for cue in ("rose petal", "rose whip", "rosa rossa", "玫瑰")
        )
    if trend_name == "Oriental Narrative":
        return any(
            cue in full_text
            for cue in (
                "oud",
                "oriental narrative",
                "incense",
                "sandalwood",
                "resinous",
                "沉香",
                "檀香",
                "焚香",
            )
        )
    return False


def _group_trend_products(
    topic: str, products: Dict[str, Any]
) -> Dict[str, List[tuple[str, Dict[str, Any]]]]:
    groups: Dict[str, List[tuple[str, Dict[str, Any]]]] = {
        name: [] for name in TREND_TAXONOMY[topic]
    }
    seen: Dict[str, set[str]] = {name: set() for name in groups}
    for section in ("heat_rankings", "new_product_radar"):
        for panel, rows in products.get(section, {}).items():
            for row in rows:
                identity_keys = _trend_identity_keys(row)
                if not identity_keys:
                    continue
                for trend_name in groups:
                    if not _matches_trend(topic, trend_name, row):
                        continue
                    if identity_keys & seen[trend_name]:
                        continue
                    groups[trend_name].append((panel, row))
                    seen[trend_name].update(identity_keys)
    return groups


def _render_trends(topic: str, products: Dict[str, Any], date_range: str) -> str:
    label = "Makeup" if topic == "makeup" else "Fragrance"
    groups = _group_trend_products(topic, products)
    ranked = sorted(
        ((name, rows) for name, rows in groups.items() if rows),
        key=lambda item: len(item[1]), reverse=True,
    )[:4]
    cards = []
    for trend_name, rows in ranked:
        names = [str(row.get("name", "")).strip() for _, row in rows if row.get("name")][:3]
        markets = sorted({panel.split()[0] for panel, _ in rows})
        signal_word = "signal" if len(rows) == 1 else "signals"
        cards.append(
            '<div class="trend-v-card"><div class="trend-v-header">'
            f'<h4><span class="heat-trend-tag">{_esc(trend_name)}</span> · {len(rows)} evidence-backed product {signal_word}</h4><span class="trend-v-arrow">▼</span></div>'
            '<div class="trend-v-body">'
            f'<div class="driver-summary">Observed in the verified {date_range} ranking and launch evidence across {", ".join(markets)}. Examples: {_esc(", ".join(names))}.</div>'
            '<div class="action-block"><div class="act-detail-text">Use this as a directional product signal; validate sales velocity and consumer demand before an NPD commitment.</div></div>'
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
        radar_panels = products.get("new_product_radar", {})
        if not monthly_evidence_available:
            panel_names = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")
            heat_panels = {panel: [] for panel in panel_names}
            radar_panels = {panel: [] for panel in panel_names}

        topic_coverage = (data.get("panel_coverage") or {}).get(topic, {})
        # Render current-month editorial sections. These must never inherit a
        # prior month's static content from the page shell.
        news_html = _render_news(topic, _topic_articles(raw_collection, topic, month_label), date_range)
        html = _replace_section(html, 1, news_html)
        trends_html = _render_trends(topic, products, date_range)
        html = _replace_section(html, 2, trends_html)

        # Render and replace Section 03
        heat_html = _render_section(
            heat_panels, lang, topic, "heat", topic_coverage.get("heat_rankings")
        )
        html = _replace_section(html, 3, heat_html)

        # Render and replace Section 04 (plus market observation area)
        radar_html = _render_section(
            radar_panels, lang, topic, "radar", topic_coverage.get("new_product_radar")
        )
        observations = (data.get("market_observation") or {}).get(topic, {})
        radar_html += _render_market_observation(topic, lang, observations)
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
