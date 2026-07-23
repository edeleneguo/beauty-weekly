#!/usr/bin/env python3
# ruff: noqa: E501
"""Reconcile source, canonical, and rendered monthly completeness."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import resolve_month  # noqa: E402

MONTH = resolve_month()
MONTH_DIR = ROOT / "data" / "months" / MONTH
REFERENCE_PATH = MONTH_DIR / "completeness_reference.json"
AUDIT_PATH = MONTH_DIR / "completeness_audit.json"
RENDERED_PAGES = {
    "makeup": ROOT / "index.html",
    "fragrance": ROOT / "fragrance.html",
}
PANEL_ORDER = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")


def _count_pattern(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text))


def _extract_panel_counts(section_html: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    headings = list(re.finditer(r"<h4[^>]*>(.*?)</h4>", section_html, re.DOTALL))
    for idx, heading in enumerate(headings):
        heading_html = heading.group(1)
        market_match = re.search(r"<span[^>]*>(US|CN)</span>", heading_html)
        tier_match = re.search(r"<span[^>]*>(LUXURY|MASSTIGE)</span>", heading_html)
        if market_match is None or tier_match is None:
            continue
        panel_key = f"{market_match.group(1)} {tier_match.group(1)}"
        start = heading.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(section_html)
        panel_html = section_html[start:end]
        counts[panel_key] = _count_pattern(panel_html, r'class="heat-item-header"')
    return counts


def _extract_section(html: str, section_num: int) -> str:
    if section_num == 1:
        pattern = (
            r'<h2\s+class="section-title">.*?<span\s+class="sec-label">Section 01</span></h2>'
            r".*?"
            r'(?=<h2\s+class="section-title">.*?<em>Trend</em>\s+Report(?:\s*<span\s+class="sec-label">Section 02</span>)?</h2>)'
        )
    elif section_num == 2:
        pattern = (
            r'<h2\s+class="section-title">.*?<em>Trend</em>\s+Report(?:\s*<span\s+class="sec-label">Section 02</span>)?</h2>'
            r".*?"
            r'(?=<h2\s+class="section-title">.*?<span\s+class="sec-label">Section 03</span>)'
        )
    elif section_num == 3:
        pattern = (
            r'<h2\s+class="section-title">.*?<span\s+class="sec-label">Section 03</span></h2>'
            r".*?"
            r'(?=<h2\s+class="section-title">.*?<span\s+class="sec-label">Section 04</span>)'
        )
    else:
        pattern = (
            r'<h2\s+class="section-title">.*?<span\s+class="sec-label">Section 04</span></h2>'
            r".*?"
            r'(?=<!--\s+APPENDIX|<div\s+class="section">\s*\n?\s*<h3)'
        )
    match = re.search(pattern, html, re.DOTALL)
    if match is None:
        raise ValueError(f"Unable to extract Section {section_num:02d}")
    return match.group(0)


def _rendered_counts(html: str) -> dict[str, Any]:
    section_01 = _extract_section(html, 1)
    section_02 = _extract_section(html, 2)
    section_03 = _extract_section(html, 3)
    section_04 = _extract_section(html, 4)
    return {
        "news_cards": _count_pattern(section_01, r'class="news-card"'),
        "trend_cards": _count_pattern(section_02, r'class="trend-v-card'),
        "heat_panels": _extract_panel_counts(section_03),
        "radar_panels": _extract_panel_counts(section_04),
        "placeholders_present": any(
            marker in html
            for marker in (
                "No verified news items",
                "No verified trend data",
            )
        ),
    }


def main() -> int:
    if not REFERENCE_PATH.exists():
        print(f"FAIL: missing completeness reference {REFERENCE_PATH}", file=sys.stderr)
        return 1

    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    report = json.loads((MONTH_DIR / "report.json").read_text(encoding="utf-8"))
    rendered = {
        topic: _rendered_counts(path.read_text(encoding="utf-8"))
        for topic, path in RENDERED_PAGES.items()
    }

    canonical_counts = {
        topic: {
            section: {
                panel: len(report["products"][topic][section][panel]) for panel in PANEL_ORDER
            }
            for section in ("heat_rankings", "new_product_radar")
        }
        for topic in ("makeup", "fragrance")
    }

    errors: list[str] = []
    for topic in ("makeup", "fragrance"):
        source_shell = reference["render_shell_counts"][topic]
        rendered_shell = rendered[topic]
        if source_shell["news_cards"] and rendered_shell["news_cards"] != source_shell["news_cards"]:
            errors.append(
                f"{topic} Section01 news mismatch: source={source_shell['news_cards']} "
                f"rendered={rendered_shell['news_cards']}"
            )
        if source_shell["trend_cards"] and rendered_shell["trend_cards"] != source_shell["trend_cards"]:
            errors.append(
                f"{topic} Section02 trends mismatch: source={source_shell['trend_cards']} "
                f"rendered={rendered_shell['trend_cards']}"
            )
        for panel in PANEL_ORDER:
            expected_heat = canonical_counts[topic]["heat_rankings"][panel]
            rendered_heat = rendered_shell["heat_panels"].get(panel, 0)
            if expected_heat != rendered_heat:
                errors.append(
                    f"{topic} Section03 {panel} mismatch: canonical={expected_heat} rendered={rendered_heat}"
                )
            expected_radar = canonical_counts[topic]["new_product_radar"][panel]
            rendered_radar = rendered_shell["radar_panels"].get(panel, 0)
            if expected_radar != rendered_radar:
                errors.append(
                    f"{topic} Section04 {panel} mismatch: canonical={expected_radar} rendered={rendered_radar}"
                )
        if rendered_shell["placeholders_present"] and source_shell["news_cards"]:
            errors.append(f"{topic} rendered page still contains placeholder empty-state content")

    audit = {
        "canonical_counts": canonical_counts,
        "errors": errors,
        "month": MONTH,
        "reference": reference,
        "rendered_counts": rendered,
        "status": "pass" if not errors else "fail",
    }
    AUDIT_PATH.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if errors:
        print("FAIL")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1

    print(f"PASS: monthly completeness audit ({MONTH})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
