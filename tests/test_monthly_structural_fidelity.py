from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTH_DIR = ROOT / "data" / "months" / "2026-06"


def _load_report() -> dict:
    return json.loads((MONTH_DIR / "report.json").read_text(encoding="utf-8"))


def _load_reference() -> dict:
    return json.loads((MONTH_DIR / "completeness_reference.json").read_text(encoding="utf-8"))


def test_cn_panels_populated_when_historical_candidates_exist():
    report = _load_report()
    reference = _load_reference()

    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel in ("CN LUXURY", "CN MASSTIGE"):
                candidate_count = reference["candidate_counts"][topic][section][panel]
                canonical_count = len(report["products"][topic][section][panel])
                if candidate_count > 0:
                    assert canonical_count > 0, (
                        f"{topic}/{section}/{panel} has historical CN candidates "
                        f"but canonical report is empty"
                    )


def test_no_suspicious_generic_detail_reuse_across_unrelated_products():
    report = _load_report()
    suspicious_phrases = {
        "sephora launch traction",
        "sephora launch topper",
        "sephora newness plus tiktok discussion",
        "june 1 retailer listing confirms launch-day availability",
    }

    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel_products in report["products"][topic][section].values():
                for product in panel_products:
                    for field in ("buzz", "brand", "key_features"):
                        value = product["detail"][field]["en"].strip().casefold()
                        if value in suspicious_phrases:
                            owners[(field, value)].add(product["name"])

    duplicated = {
        key: sorted(names)
        for key, names in owners.items()
        if len(names) > 1
    }
    assert duplicated == {}, f"Suspicious generic detail reuse detected: {duplicated}"


def test_radar_filter_keeps_verified_products_without_trend_badge():
    spec = importlib.util.spec_from_file_location("render_module", ROOT / "build" / "render.py")
    render = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(render)
    products = [
        {"name": "Visible Radar Product", "score": 88, "quarantine_status": "verified"},
        {"name": "Hidden Radar Product", "score": 88, "quarantine_status": "out-of-window"},
    ]
    filtered = render._filter_panel_products(products, "radar")
    assert [product["name"] for product in filtered] == ["Visible Radar Product"]


def test_monthly_templates_have_sequential_section_labels():
    for template_name in ("index.html", "fragrance.html"):
        html = (ROOT / "templates" / "pages" / template_name).read_text(encoding="utf-8")
        positions = [html.index(f"Section 0{i}") for i in range(1, 5)]
        assert positions == sorted(positions), f"{template_name} section labels are out of order"


def test_structural_fidelity_manifest_script_writes_required_sections():
    result = subprocess.run(
        [sys.executable, str(ROOT / "build" / "structural_fidelity_manifest.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    manifest_path = MONTH_DIR / "structural_fidelity_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "historical_weeks" in manifest
    assert "current_rendered" in manifest
    assert "parity_audit" in manifest


def test_monthly_radar_trend_inference_restores_clear_historical_signals_only():
    report = _load_report()

    def radar_lookup(topic: str, panel: str, name: str) -> dict:
        for product in report["products"][topic]["new_product_radar"][panel]:
            if product["name"] == name:
                return product
        raise AssertionError(f"Missing radar product: {topic}/{panel}/{name}")

    assert (
        radar_lookup("fragrance", "US MASSTIGE", "Phlur Rose Whip EDP")["trend"]["tag"]
        == "Rose Revival"
    )
    assert (
        radar_lookup("fragrance", "US LUXURY", "Bvlgari Eau Parfumée Thé Impérial")["trend"][
            "tag"
        ]
        == "Matcha Fragrance"
    )
    assert (
        radar_lookup("makeup", "CN LUXURY", "MAOGEPING Luxurious Radiant Foundation Cream")[
            "trend"
        ]["tag"]
        == "Skincare Foundation"
    )
    assert (
        radar_lookup("makeup", "US MASSTIGE", "MAC x Chappell Roan VIVA GLAM")["trend"][
            "tag"
        ]
        == "Functional Lip"
    )

    assert not radar_lookup("fragrance", "US LUXURY", "Tom Ford Taormina Orange EDP").get(
        "trend_badge"
    )
    assert not radar_lookup("makeup", "US LUXURY", "Marc Jacobs Drawn This Way Gel Eyeliner").get(
        "trend_badge"
    )
