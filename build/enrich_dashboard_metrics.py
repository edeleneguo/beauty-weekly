#!/usr/bin/env python3
"""Add dashboard explainability metrics to a monthly canonical report.

This is a deterministic enrichment layer for the dashboard. It does not claim
that historical scores are raw-data recomputable; instead, it allocates each
displayed score across the agreed business weights so users can see why a
product is hot and where the data is strong or thin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import month_data_dir, resolve_month  # noqa: E402

WEIGHTS = [
    {
        "id": "sales_momentum",
        "label": "Sales Momentum",
        "weight": 0.40,
        "max_points": 40,
        "evidence": "Sales, bestseller, ranking, sell-out, restock, and platform proxy signals.",
    },
    {
        "id": "buzz_momentum",
        "label": "Buzz Momentum",
        "weight": 0.30,
        "max_points": 30,
        "evidence": "Social discussion, creator/editor coverage, and media visibility.",
    },
    {
        "id": "review_rating",
        "label": "Review / Rating",
        "weight": 0.20,
        "max_points": 20,
        "evidence": "Ratings, review volume, expert tests, vote counts, and user feedback.",
    },
    {
        "id": "trend_fit",
        "label": "Trend Fit",
        "weight": 0.10,
        "max_points": 10,
        "evidence": "Fit with the month's active trend taxonomy and new-product context.",
    },
]

METHODOLOGY = (
    "Weighted dashboard explanation: Sales Momentum 40% + Buzz Momentum 30% + "
    "Review/Rating 20% + Trend Fit 10%. Historical monthly scores remain "
    "non-recomputable until raw platform sales/review/social time-series are collected."
)

SALES_RE = re.compile(
    r"\b(?:sales|sold|bestseller|top\s?\d*|ranking|rank|gmv|618|monthly|velocity|"
    r"restock|sell-?out|units|sephora top|tmall|douyin sales|sales data)\b|月销|销量|榜",
    re.I,
)
BUZZ_RE = re.compile(
    r"\b(?:tiktok|douyin|xiaohongshu|little red book|weibo|instagram|allure|vogue|"
    r"cosmopolitan|harper|editor|media|viral|fragrantica|parfumo|girlstyle|smzdm|"
    r"toutiao|baijiahao|hypebae|byrdie|instyle)\b",
    re.I,
)
REVIEW_RE = re.compile(
    r"\b(?:review|reviews|rating|rated|votes|tested|test|score|stars|editor choice|"
    r"feedback|sentiment|positive|negative)\b|评价|口碑|测评",
    re.I,
)

PRODUCT_PAGE_HINTS = (
    "/product/",
    "/products/",
    "/p/",
    "/shop/product/",
    "/makeup/",
    "/fragrances/",
    "/fragrance/",
)
EVIDENCE_PREFIX_RE = re.compile(r"^(?:archived source observed|evidence-backed observed)", re.I)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_blob(product: dict) -> str:
    detail = product.get("detail", {})
    parts = [
        product.get("name", ""),
        product.get("category_badge", ""),
        detail.get("key_features", {}).get("en", ""),
        detail.get("buzz", {}).get("en", ""),
        detail.get("brand", {}).get("en", ""),
        detail.get("price_link", {}).get("en", ""),
    ]
    return " ".join(str(part) for part in parts if part)


def _strengths(product: dict) -> dict[str, float]:
    blob = _text_blob(product)
    has_trend = bool(product.get("trend_badge") or product.get("trend"))
    has_new = bool(product.get("new_badge") or product.get("launch_evidence"))
    buzz_hits = len(BUZZ_RE.findall(blob))
    sales_hits = len(SALES_RE.findall(blob))
    review_hits = len(REVIEW_RE.findall(blob))
    return {
        "sales_momentum": 0.85 + min(sales_hits, 4) * 0.12,
        "buzz_momentum": 0.85 + min(buzz_hits, 5) * 0.10,
        "review_rating": 0.78 + min(review_hits, 4) * 0.12,
        "trend_fit": 1.25 if has_trend else (1.05 if has_new else 0.75),
    }


def _allocate_points(score: int, strengths: dict[str, float]) -> list[dict]:
    weighted = []
    for component in WEIGHTS:
        raw = component["max_points"] * strengths[component["id"]]
        weighted.append((component, raw))
    total_raw = sum(raw for _component, raw in weighted) or 1.0

    allocations = []
    remaining = score
    for component, raw in weighted:
        exact = score * raw / total_raw
        points = min(component["max_points"], int(exact))
        allocations.append({"component": component, "points": points, "fraction": exact - points})
        remaining -= points

    while remaining > 0:
        candidates = [
            item
            for item in allocations
            if item["points"] < item["component"]["max_points"]
        ]
        if not candidates:
            break
        candidates.sort(key=lambda item: item["fraction"], reverse=True)
        candidates[0]["points"] += 1
        candidates[0]["fraction"] = 0
        remaining -= 1

    return [
        {
            "id": item["component"]["id"],
            "label": item["component"]["label"],
            "weight": item["component"]["weight"],
            "max_points": item["component"]["max_points"],
            "points": item["points"],
            "evidence": item["component"]["evidence"],
        }
        for item in allocations
    ]


def _link_type(product: dict) -> str:
    price_link = product.get("detail", {}).get("price_link", {})
    link = str(price_link.get("link") or "")
    price_text = str(price_link.get("en") or "")
    parsed = urlparse(link)
    path = parsed.path.casefold()
    if "github.com" in parsed.netloc and "/archive/" in path:
        return "archive_evidence"
    if EVIDENCE_PREFIX_RE.search(price_text):
        return "editorial_evidence"
    if any(hint in path for hint in PRODUCT_PAGE_HINTS):
        return "product_page"
    return "evidence_link"


def _data_quality(product: dict) -> dict:
    detail = product.get("detail", {})
    evidence = (product.get("launch_evidence") or {}).get("evidence") or {}
    coverage = {
        "price": bool(detail.get("price_link", {}).get("en")),
        "link": bool(detail.get("price_link", {}).get("link")),
        "features": bool(detail.get("key_features", {}).get("en")),
        "buzz": bool(detail.get("buzz", {}).get("en")),
        "positioning": bool(detail.get("brand", {}).get("en")),
        "launch_evidence": bool(evidence.get("url")),
    }
    missing = [field for field, present in coverage.items() if not present]
    coverage_score = round(sum(coverage.values()) / len(coverage) * 100)
    source_type = str(evidence.get("type") or "unknown")
    link_type = _link_type(product)
    if link_type == "product_page":
        note = "Direct product page available."
    elif link_type == "archive_evidence":
        note = "Historical archive used as explicit evidence fallback."
    elif link_type == "editorial_evidence":
        note = "Editorial evidence used as explicit fallback where product page is unstable."
    else:
        note = "Evidence link available; review for direct product-page upgrade."
    return {
        "source_type": source_type,
        "link_type": link_type,
        "coverage_score": coverage_score,
        "coverage": coverage,
        "missing_fields": missing,
        "note": note,
    }


def enrich_report(report: dict) -> None:
    for topic_data in report.get("products", {}).values():
        for section_data in topic_data.values():
            for products in section_data.values():
                for product in products:
                    score = int(product.get("score") or 0)
                    product["score_breakdown"] = {
                        "methodology": METHODOLOGY,
                        "recomputable": False,
                        "total": score,
                        "components": _allocate_points(score, _strengths(product)),
                    }
                    product["data_quality"] = _data_quality(product)


def enrich_scoring(scoring: dict) -> None:
    scoring["display_breakdown_policy"] = {
        "version": "dashboard-explainability-v1",
        "status": "display_explanation_not_raw_recompute",
        "methodology": METHODOLOGY,
        "components": WEIGHTS,
    }
    missing = scoring.setdefault("missing_components", [])
    raw_gap = (
        "raw component time-series - sales, social, review, and trend inputs not yet "
        "collected as normalized numeric series"
    )
    if raw_gap not in missing:
        missing.append(raw_gap)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default=None, help="Target month YYYY-MM")
    args = parser.parse_args()

    month = resolve_month(args.month)
    data_dir = Path(month_data_dir(month))
    report_path = data_dir / "report.json"
    scoring_path = data_dir / "scoring.json"
    manifest_path = data_dir / "manifest.json"

    report = _read_json(report_path)
    scoring = _read_json(scoring_path)
    manifest = _read_json(manifest_path)

    enrich_report(report)
    enrich_scoring(scoring)

    _write_json(report_path, report)
    _write_json(scoring_path, scoring)

    manifest["canonical_hash"] = _hash(report_path)
    manifest["scoring_hash"] = _hash(scoring_path)
    _write_json(manifest_path, manifest)

    print(f"Enriched dashboard metrics for {month}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
