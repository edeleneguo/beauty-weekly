#!/usr/bin/env python3
"""Audit visible monthly product quality for the June monthly report.

This audit is intentionally narrower than schema validation. It only checks
product-facing fields rendered into the English pages and avoids flagging
metadata-only gaps such as empty ``name_cn`` or ``category_badge_cn``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import month_report_path, resolve_month  # noqa: E402

CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
SIZE_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ml|mL|ML|fl oz|oz|g|gram|grams)\b", re.I)
PRICE_PATTERN = re.compile(r"(?:[$€£¥]|USD|CAD|HKD|SGD|AED|RMB|CNY)")
PRICE_GAP_PATTERN = re.compile(
    r"\bprice\b.*\b(?:pending|not (?:publicly )?disclosed|not announced)\b",
    re.I,
)
SIZE_GAP_PATTERN = re.compile(
    r"\b(?:bottle size|size|volume|format)\b.*\b"
    r"(?:pending|not (?:publicly )?disclosed|not announced)\b",
    re.I,
)
GENERIC_CATEGORY_PATTERN = re.compile(r"^(?:edp|edt|perfume|fragrance|solid)$", re.I)
GENERIC_BUZZ_PATTERNS = (
    re.compile(r"^seasonal\b", re.I),
    re.compile(r"^limited edition\b", re.I),
    re.compile(r"^new release\b", re.I),
    re.compile(r"^brand new category\b", re.I),
    re.compile(r"^brand return new product line\b", re.I),
    re.compile(r"^new product line\b", re.I),
)
LAUNCH_TYPE_HINTS = (
    "launch",
    "new",
    "limited",
    "edition",
    "flanker",
    "travel",
    "solid",
    "mist",
    "preorder",
    "on-sale",
    "refill",
    "line",
    "collection",
    "duo",
    "shade",
    "series",
    "collab",
    "collaboration",
)

EXPECTED_SCORE_COMPONENTS = {
    "sales_momentum": ("Sales Momentum", 0.40, 40),
    "buzz_momentum": ("Buzz Momentum", 0.30, 30),
    "review_rating": ("Review / Rating", 0.20, 20),
    "trend_fit": ("Trend Fit", 0.10, 10),
}


def _load_report(month: str) -> dict:
    report_path = Path(month_report_path(month))
    return json.loads(report_path.read_text(encoding="utf-8"))


def _iter_products(report: dict):
    products = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, items in products.get(topic, {}).get(section, {}).items():
                for idx, product in enumerate(items, start=1):
                    launch_evidence = product.get("launch_evidence") or {}
                    qs = product.get("quarantine_status") or launch_evidence.get(
                        "quarantine_status"
                    )
                    if section == "new_product_radar" and qs and qs != "verified":
                        continue
                    yield topic, section, panel, idx, product


def _loc(topic: str, section: str, panel: str, idx: int, product: dict) -> str:
    return f"{topic}/{section}/{panel}[{idx}] {product.get('name', '?')}"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


_TMALL_STORE_RE = re.compile(r"\.tmall\.com\s*/?\s*$", re.I)
_SEPHORA_HOME_RE = re.compile(r"^https?://(?:www\.)?sephora\.com\s*/?\s*$", re.I)
_GENERIC_PATHS = {
    "beauty",
    "bestsellers",
    "capsule",
    "collection",
    "collections",
    "fragrance",
    "makeup",
    "new-arrival",
    "new-arrivals",
    "perfume",
    "product",
    "products",
    "sale",
    "shop-all",
    "skincare",
    "xilie",
}
_LOCALE_HOME_RE = re.compile(
    r"^https?://(?:www\.)?[a-z0-9-]+\.(?:cn|com\.cn|co\.cn)(?:/zh(?:_cn)?/beauty/?|/?\s*)$",
    re.I,
)
_EVIDENCE_URL_RE = re.compile(r"github\.com/.+/blob/.+/archive/", re.I)
_EVIDENCE_PRICE_RE = re.compile(
    r"^(?:archived source observed|evidence-backed observed|evidence source)",
    re.I,
)


def _is_generic_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return True
    path = (parsed.path or "/").strip("/")
    if not path:
        return True
    if _TMALL_STORE_RE.search(url):
        return True
    if _SEPHORA_HOME_RE.match(url):
        return True
    if _LOCALE_HOME_RE.match(url):
        return True
    normalized_path = path.casefold().rstrip("/")
    if normalized_path in _GENERIC_PATHS:
        return True
    if normalized_path.endswith(("product-list", "/xilie", "-collection.html")):
        return True
    if "/collections/" in f"/{normalized_path}/" or "/capsule/" in f"/{normalized_path}/":
        return True
    return normalized_path.startswith("pages/") and normalized_path.endswith(
        ("-collection", "-collections")
    )


def _is_evidence_url(url: str) -> bool:
    return bool(_EVIDENCE_URL_RE.search(url))


def _is_explicit_evidence_link(product: dict, link: str) -> bool:
    """Allow article/archive evidence links when the visible copy says so.

    Monthly dashboards sometimes need a credible article, RSS result, or
    historical archive as the best available evidence, especially for CN
    platforms where direct product pages are unstable. Those links are allowed
    only when they are the product's cited evidence URL and the price text makes
    the fallback explicit instead of presenting it as a product page.
    """
    price_text = product.get("detail", {}).get("price_link", {}).get("en", "").strip()
    evidence = (product.get("launch_evidence") or {}).get("evidence") or {}
    evidence_type = str(evidence.get("type") or "").casefold()
    evidence_url = str(evidence.get("url") or "").strip()
    if link != evidence_url:
        return False
    if evidence_type not in {"editorial", "repo_snapshot", "article", "news", "rss_result"}:
        return False
    return bool(_EVIDENCE_PRICE_RE.search(price_text))


def _visible_fields(product: dict, section: str) -> dict[str, str]:
    detail = product.get("detail", {})
    return {
        "name": product.get("name", ""),
        "category_badge": product.get("category_badge", ""),
        "price_text": detail.get("price_link", {}).get("en", ""),
        "link": detail.get("price_link", {}).get("link", ""),
        "key_features": detail.get("key_features", {}).get("en", ""),
        "buzz": detail.get("buzz", {}).get("en", ""),
        "launch_or_brand": detail.get("brand", {}).get("en", ""),
        "section": section,
    }


def audit_visible_cjk(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        fields = _visible_fields(product, section)
        for label, value in fields.items():
            if label in {"section"}:
                continue
            if value and CJK_PATTERN.search(value):
                errors.append(f"{_loc(topic, section, panel, idx, product)}: {label} contains CJK")
    return errors


def audit_empty_visible_fields(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        fields = _visible_fields(product, section)
        for label in (
            "name",
            "category_badge",
            "price_text",
            "link",
            "key_features",
            "buzz",
            "launch_or_brand",
        ):
            if not fields[label].strip():
                errors.append(f"{_loc(topic, section, panel, idx, product)}: empty {label}")
    return errors


def audit_duplicate_or_generic_buzz(report: dict) -> list[str]:
    errors: list[str] = []
    owners: dict[str, list[tuple[str, str, str, str, bool]]] = defaultdict(list)
    for topic, section, panel, idx, product in _iter_products(report):
        buzz = product.get("detail", {}).get("buzz", {}).get("en", "").strip()
        if not buzz:
            continue
        launch_evidence = product.get("launch_evidence") or {}
        owners[buzz.casefold()].append(
            (
                _loc(topic, section, panel, idx, product),
                topic,
                section,
                _normalize_name(product.get("name", "")),
                (product.get("quarantine_status") or launch_evidence.get("quarantine_status"))
                == "verified",
            )
        )
        for pattern in GENERIC_BUZZ_PATTERNS:
            if pattern.search(buzz):
                errors.append(f"{_loc(topic, section, panel, idx, product)}: generic buzz '{buzz}'")
                break
    for buzz, records in owners.items():
        if len(records) <= 1:
            continue
        same_verified_fragrance_sku = (
            all(topic == "fragrance" for _, topic, _, _, _ in records)
            and all(verified for _, _, _, _, verified in records)
            and len({norm_name for _, _, _, norm_name, _ in records}) == 1
            and {section for _, _, section, _, _ in records}
            <= {"heat_rankings", "new_product_radar"}
        )
        if not same_verified_fragrance_sku:
            errors.append(f"duplicate buzz reused across products: '{buzz}'")
    return errors


def audit_urls(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        link = product.get("detail", {}).get("price_link", {}).get("link", "").strip()
        if not link:
            continue
        if _is_evidence_url(link) or _is_explicit_evidence_link(product, link):
            continue
        if _is_generic_url(link):
            errors.append(
                f"{_loc(topic, section, panel, idx, product)}: non-direct or generic URL {link}"
            )
    return errors


def audit_rank_order(report: dict) -> list[str]:
    errors: list[str] = []
    products = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, items in products.get(topic, {}).get(section, {}).items():
                visible = []
                for product in items:
                    if product.get("score", 0) == 0:
                        continue
                    launch_evidence = product.get("launch_evidence") or {}
                    qs = product.get("quarantine_status") or launch_evidence.get(
                        "quarantine_status"
                    )
                    if section == "new_product_radar" and qs in ("out-of-window", "unverified"):
                        continue
                    visible.append(product)
                ranks = [product.get("rank") for product in visible]
                expected = list(range(1, len(visible) + 1))
                if ranks != expected:
                    errors.append(
                        f"{topic}/{section}/{panel}: ranks {ranks} are not sequential {expected}"
                    )
                scores = [float(product.get("score") or 0) for product in visible]
                if scores != sorted(scores, reverse=True):
                    errors.append(
                        f"{topic}/{section}/{panel}: scores {scores} are not descending"
                    )
    return errors


def audit_category_specificity(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        category = product.get("category_badge", "").strip()
        if not category:
            continue
        if GENERIC_CATEGORY_PATTERN.fullmatch(category) or PRICE_PATTERN.search(category):
            errors.append(
                f"{_loc(topic, section, panel, idx, product)}: generic category '{category}'"
            )
    return errors


def audit_market_tier(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        expected_market, expected_tier = panel.split(" ", 1)
        if product.get("market") != expected_market or product.get("tier") != expected_tier:
            errors.append(
                f"{_loc(topic, section, panel, idx, product)}: market/tier mismatch "
                f"{product.get('market')}/{product.get('tier')}"
            )
    return errors


def audit_trend_rationale(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        if section != "new_product_radar" or not product.get("trend_badge"):
            continue
        trend = product.get("trend") or {}
        rationale = product.get("trend_rationale") or trend.get("rationale") or ""
        if not rationale.strip():
            errors.append(
                f"{_loc(topic, section, panel, idx, product)}: trend badge without rationale"
            )
    return errors


def audit_heat_new_parity(report: dict) -> list[str]:
    errors: list[str] = []
    radar_names: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for topic, section, _panel, _idx, product in _iter_products(report):
        if section != "new_product_radar":
            continue
        radar_names[(topic, product.get("market", ""), product.get("tier", ""))].add(
            _normalize_name(product.get("name", ""))
        )
    for topic, section, panel, idx, product in _iter_products(report):
        if section != "heat_rankings" or not product.get("new_badge"):
            continue
        key = (topic, product.get("market", ""), product.get("tier", ""))
        if _normalize_name(product.get("name", "")) not in radar_names.get(key, set()):
            errors.append(
                f"{_loc(topic, section, panel, idx, product)}: NEW heat item missing "
                "same-market radar"
            )
    return errors


def audit_radar_name_alignment(report: dict) -> list[str]:
    errors: list[str] = []
    heat_new_names: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for topic, section, _panel, _idx, product in _iter_products(report):
        if section == "heat_rankings" and product.get("new_badge"):
            heat_new_names[(topic, product.get("market", ""), product.get("tier", ""))].append(
                product.get("name", "")
            )
    for topic, section, panel, idx, product in _iter_products(report):
        if topic != "fragrance" or section != "new_product_radar":
            continue
        current = _normalize_name(product.get("name", ""))
        if len(current) < 8:
            continue
        key = (topic, product.get("market", ""), product.get("tier", ""))
        for heat_name in heat_new_names.get(key, []):
            heat_norm = _normalize_name(heat_name)
            if heat_norm.endswith(current) and heat_norm != current:
                errors.append(
                    f"{_loc(topic, section, panel, idx, product)}: radar name likely missing "
                    f"brand prefix vs heat '{heat_name}'"
                )
                break
    return errors


def audit_fragrance_price_and_launch(report: dict) -> list[str]:
    errors: list[str] = []
    for topic, section, panel, idx, product in _iter_products(report):
        if topic != "fragrance":
            continue
        price = product.get("detail", {}).get("price_link", {}).get("en", "").strip()
        launch_text = product.get("detail", {}).get("brand", {}).get("en", "").strip()
        if section == "new_product_radar":
            has_price_or_disclosed_gap = bool(
                PRICE_PATTERN.search(price) or PRICE_GAP_PATTERN.search(price)
            )
            has_size_or_disclosed_gap = bool(
                SIZE_PATTERN.search(price) or SIZE_GAP_PATTERN.search(price)
            )
            if not has_price_or_disclosed_gap or not has_size_or_disclosed_gap:
                errors.append(
                    f"{_loc(topic, section, panel, idx, product)}: fragrance radar price needs "
                    "currency and size, or an explicit disclosure gap for each"
                )
            lowered = launch_text.casefold()
            if not any(hint in lowered for hint in LAUNCH_TYPE_HINTS):
                errors.append(
                    f"{_loc(topic, section, panel, idx, product)}: launch/category text lacks "
                    "specific launch type"
                )
    return errors


def audit_score_breakdown(report: dict) -> list[str]:
    errors: list[str] = []
    expected_ids = set(EXPECTED_SCORE_COMPONENTS)
    for topic, section, panel, idx, product in _iter_products(report):
        loc = _loc(topic, section, panel, idx, product)
        score = int(product.get("score") or 0)
        breakdown = product.get("score_breakdown")
        if not breakdown:
            errors.append(f"{loc}: missing score_breakdown")
            continue
        if breakdown.get("recomputable") is not False:
            errors.append(f"{loc}: score_breakdown must mark historical scores non-recomputable")
        if int(breakdown.get("total") or -1) != score:
            errors.append(f"{loc}: score_breakdown total does not match score {score}")

        components = breakdown.get("components") or []
        component_ids = {component.get("id") for component in components}
        if component_ids != expected_ids:
            errors.append(f"{loc}: unexpected score components {sorted(component_ids)}")
            continue

        point_total = 0
        weight_total = 0.0
        for component in components:
            component_id = component.get("id")
            expected_label, expected_weight, expected_max = EXPECTED_SCORE_COMPONENTS[component_id]
            points = int(component.get("points") or 0)
            max_points = int(component.get("max_points") or 0)
            weight = float(component.get("weight") or 0)
            point_total += points
            weight_total += weight
            if component.get("label") != expected_label:
                errors.append(f"{loc}: {component_id} label mismatch")
            if abs(weight - expected_weight) > 0.000001:
                errors.append(f"{loc}: {component_id} weight mismatch")
            if max_points != expected_max:
                errors.append(f"{loc}: {component_id} max_points mismatch")
            if points > max_points:
                errors.append(f"{loc}: {component_id} points exceed max_points")
            if not str(component.get("evidence") or "").strip():
                errors.append(f"{loc}: {component_id} missing evidence description")
        if point_total != score:
            errors.append(f"{loc}: score component points {point_total} do not sum to {score}")
        if abs(weight_total - 1.0) > 0.000001:
            errors.append(f"{loc}: score component weights {weight_total} do not sum to 1.0")

        data_quality = product.get("data_quality")
        if not data_quality:
            errors.append(f"{loc}: missing data_quality")
            continue
        coverage_score = data_quality.get("coverage_score")
        if not isinstance(coverage_score, int) or not 0 <= coverage_score <= 100:
            errors.append(f"{loc}: invalid data_quality coverage_score")
        coverage = data_quality.get("coverage") or {}
        for field in ("price", "link", "features", "buzz", "positioning", "launch_evidence"):
            if field not in coverage:
                errors.append(f"{loc}: data_quality coverage missing {field}")
        if not str(data_quality.get("link_type") or "").strip():
            errors.append(f"{loc}: missing data_quality link_type")
    return errors


def audit_english_page_shells(month: str) -> list[str]:
    errors: list[str] = []
    shell_dir = Path(month_report_path(month)).parent / "page_shells"
    for name in ("index.html", "fragrance.html"):
        path = shell_dir / name
        if not path.exists():
            continue
        matches = sorted(set(CJK_PATTERN.findall(path.read_text(encoding="utf-8"))))
        if matches:
            errors.append(f"{name}: visible shell contains CJK: {', '.join(matches)}")
    return errors


def run(month: str) -> list[tuple[str, list[str]]]:
    report = _load_report(month)
    checks = [
        ("visible_cjk", audit_visible_cjk(report)),
        ("empty_visible_fields", audit_empty_visible_fields(report)),
        ("duplicate_or_generic_buzz", audit_duplicate_or_generic_buzz(report)),
        ("direct_urls", audit_urls(report)),
        ("rank_order", audit_rank_order(report)),
        ("category_specificity", audit_category_specificity(report)),
        ("market_tier", audit_market_tier(report)),
        ("trend_rationale", audit_trend_rationale(report)),
        ("heat_new_parity", audit_heat_new_parity(report)),
        ("radar_name_alignment", audit_radar_name_alignment(report)),
        ("fragrance_price_and_launch", audit_fragrance_price_and_launch(report)),
        ("score_breakdown", audit_score_breakdown(report)),
        ("english_page_shells", audit_english_page_shells(month)),
    ]
    return [(name, errors) for name, errors in checks if errors]


def main() -> int:
    month = resolve_month()
    failures = run(month)
    print(f"Product quality audit for {month}")
    if not failures:
        print("PASS: no visible product-quality issues found")
        return 0

    total = 0
    for name, errors in failures:
        print(f"\n[{name}] {len(errors)} issue(s)")
        for error in errors:
            print(f"  - {error}")
        total += len(errors)
    print(f"\nFAIL: {total} product-quality issue(s) found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
