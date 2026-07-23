#!/usr/bin/env python3
# ruff: noqa: E501
"""Generate a structural fidelity manifest for the June 2026 historical restore."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MONTH = "2026-06"
MONTH_DIR = ROOT / "data" / "months" / MONTH
REPORT_PATH = MONTH_DIR / "report.json"
REFERENCE_PATH = MONTH_DIR / "completeness_reference.json"
MANIFEST_PATH = MONTH_DIR / "structural_fidelity_manifest.json"
RENDERED_PAGES = {
    "makeup": ROOT / "index.html",
    "fragrance": ROOT / "fragrance.html",
}
PANEL_ORDER = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")


def _load_module(relative_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module at {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _load_module("build/audit_monthly_completeness.py", "audit_monthly_completeness")
RESTORE = _load_module("build/restore_june_historical.py", "restore_june_historical")


def _rendered_features(html: str) -> dict[str, Any]:
    section_01 = AUDIT._extract_section(html, 1)
    section_02 = AUDIT._extract_section(html, 2)
    section_03 = AUDIT._extract_section(html, 3)
    section_04 = AUDIT._extract_section(html, 4)
    return {
        "news_cards": len(__import__("re").findall(r'class="news-card"', section_01)),
        "trend_cards": len(__import__("re").findall(r'class="trend-v-card', section_02)),
        "heat_panel_counts": AUDIT._extract_panel_counts(section_03),
        "radar_panel_counts": AUDIT._extract_panel_counts(section_04),
        "feature_flags": {
            "category_badges": "heat-cat-badge" in html,
            "trend_badges": "heat-trend-badge" in html,
            "trend_tags": "heat-trend-tag" in html,
            "expandable_detail_cells": "heat-detail-grid" in html,
            "expandable_rationale": "<details" in html,
        },
    }


def _panel_products(report: dict[str, Any], topic: str, section: str, panel: str) -> list[dict[str, Any]]:
    return report["products"][topic][section][panel]


def _panel_dom_count(rendered: dict[str, Any], section: str, panel: str) -> int:
    key = "heat_panel_counts" if section == "heat_rankings" else "radar_panel_counts"
    return rendered[key].get(panel, 0)


def _detail_completeness(products: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"price_link": 0, "key_features": 0, "buzz": 0, "brand": 0}
    for product in products:
        for field in counts:
            value = product["detail"][field]["en"]
            if value or product["detail"][field].get("link"):
                counts[field] += 1
    return counts


def main() -> int:
    reference = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    recovered_payload = json.loads((MONTH_DIR / "recovered_candidates.json").read_text(encoding="utf-8"))
    recovered_candidates = recovered_payload["candidates"]
    rendered = {
        topic: _rendered_features(path.read_text(encoding="utf-8"))
        for topic, path in RENDERED_PAGES.items()
    }

    parity_audit: dict[str, Any] = {}
    for topic in ("makeup", "fragrance"):
        parity_audit[topic] = {}
        for section in ("heat_rankings", "new_product_radar"):
            parity_audit[topic][section] = {}
            for panel in PANEL_ORDER:
                ranked_candidates = RESTORE._ranked_candidates(
                    recovered_candidates,
                    topic=topic,
                    section=section,
                    panel=panel,
                )
                selected_products = _panel_products(report, topic, section, panel)
                parity_audit[topic][section][panel] = {
                    "source_count": reference["source_counts"][topic][section][panel],
                    "candidate_count": reference["candidate_counts"][topic][section][panel],
                    "canonical_count": reference["canonical_counts"][topic][section][panel],
                    "dom_count": _panel_dom_count(rendered[topic], section, panel),
                    "included_products": [product["name"] for product in selected_products],
                    "excluded_products": [
                        candidate["product_name"]
                        for candidate in ranked_candidates[reference["candidate_counts"][topic][section][panel] :]
                    ],
                    "exclusion_reason": reference["exclusions"][topic][section][panel]["reason"],
                    "detail_completeness": _detail_completeness(selected_products),
                }

    manifest = {
        "month": MONTH,
        "historical_snapshot": reference["historical_snapshot"],
        "historical_snapshot_url": reference["historical_snapshot_url"],
        "historical_weeks": reference["source_manifest"]["per_week"],
        "current_rendered": rendered,
        "source_counts": reference["source_counts"],
        "candidate_counts": reference["candidate_counts"],
        "canonical_counts": reference["canonical_counts"],
        "render_shell_counts": reference["render_shell_counts"],
        "parity_audit": parity_audit,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote structural fidelity manifest: {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
