from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTH_DIR = ROOT / "data" / "months" / "2026-06"


def _read(name: str) -> dict:
    return json.loads((MONTH_DIR / name).read_text(encoding="utf-8"))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_reviewed_backfill_meets_cn_radar_soft_floors():
    report = _read("report.json")
    makeup = report["products"]["makeup"]["new_product_radar"]
    fragrance = report["products"]["fragrance"]["new_product_radar"]

    assert len(makeup["CN LUXURY"]) + len(makeup["CN MASSTIGE"]) >= 8
    assert len(fragrance["CN LUXURY"]) + len(fragrance["CN MASSTIGE"]) >= 4


def test_reviewed_backfill_products_have_graded_in_window_evidence():
    report = _read("report.json")
    audit = _read("cn_radar_backfill.json")
    approved = {candidate["name"] for candidate in audit["approved"]}

    found = {}
    for topic in ("makeup", "fragrance"):
        for panel in ("CN LUXURY", "CN MASSTIGE"):
            for product in report["products"][topic]["new_product_radar"][panel]:
                if product["name"] in approved:
                    found[product["name"]] = product

    assert found.keys() == approved
    for product in found.values():
        evidence = product["launch_evidence"]
        assert evidence["quarantine_status"] == "verified"
        assert evidence["evidence_grade"] in {"A", "B", "C"}
        assert "2026-06-01" <= evidence["launch_date"] <= "2026-06-30"
        assert not evidence["evidence"]["url"].startswith("https://news.google.com/")


def test_rejected_candidates_are_not_backfilled():
    report = _read("report.json")
    audit = _read("cn_radar_backfill.json")
    names = {
        product["name"]
        for topic in ("makeup", "fragrance")
        for panel in ("CN LUXURY", "CN MASSTIGE")
        for product in report["products"][topic]["new_product_radar"][panel]
    }
    assert names.isdisjoint({candidate["candidate"] for candidate in audit["rejected"]})


def test_fragrance_quality_audit_accepts_explicit_price_and_size_gaps():
    module = _load_script("audit_product_quality")
    report = {
        "products": {
            "makeup": {"heat_rankings": {}, "new_product_radar": {}},
            "fragrance": {
                "heat_rankings": {},
                "new_product_radar": {
                    "CN LUXURY": [
                        {
                            "name": "Reviewed Launch",
                            "market": "CN",
                            "tier": "LUXURY",
                            "score": 80,
                            "detail": {
                                "brand": {"en": "New fragrance launch"},
                                "price_link": {
                                    "en": "Price and bottle size not publicly disclosed"
                                },
                            },
                            "launch_evidence": {"quarantine_status": "verified"},
                        }
                    ]
                },
            },
        }
    }
    assert module.audit_fragrance_price_and_launch(report) == []


def test_backfill_merge_preserves_generated_product_fields():
    module = _load_script("apply_cn_radar_backfill")
    candidate = _read("cn_radar_backfill.json")["approved"][0]
    report = {
        "products": {
            topic: {
                "new_product_radar": {panel: [] for panel in module.PANELS},
            }
            for topic in module.TOPICS
        }
    }
    existing = module._canonical_product(candidate, "earlier")
    existing["data_quality"] = {"coverage_score": 100}
    existing["score_breakdown"] = {"status": "generated"}
    report["products"][candidate["topic"]]["new_product_radar"][
        candidate["panel"]
    ].append(existing)

    module._merge_report(report, [candidate], "reviewed")

    product = report["products"][candidate["topic"]]["new_product_radar"][
        candidate["panel"]
    ][0]
    assert product["data_quality"] == {"coverage_score": 100}
    assert product["score_breakdown"] == {"status": "generated"}
    assert product["launch_evidence"]["evidence"]["checked_at"] == "reviewed"


def test_backfill_evidence_grades_render_in_published_pages():
    makeup_html = (ROOT / "index.html").read_text(encoding="utf-8")
    fragrance_html = (ROOT / "fragrance.html").read_text(encoding="utf-8")

    assert "Grade C · 2026-06-24 · first verified mention" in makeup_html
    assert "Grade B · 2026-06-16 · first listing" in fragrance_html
