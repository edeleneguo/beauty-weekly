"""Deterministic product identity, tier dedupe, and dashboard label rules."""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any

TREND_TAXONOMY = {
    "makeup": ("Skincare Foundation", "Functional Lip", "Low-Saturation Pastel"),
    "fragrance": (
        "Milky Musk",
        "Matcha Fragrance",
        "Rose Revival",
        "Oriental Narrative",
    ),
}

TREND_CN = {
    "Skincare Foundation": "养肤底妆趋势",
    "Functional Lip": "唇部功效化趋势",
    "Low-Saturation Pastel": "低饱和粉彩趋势",
    "Milky Musk": "乳感麝香趋势",
    "Matcha Fragrance": "抹茶香水趋势",
    "Rose Revival": "玫瑰复兴趋势",
    "Oriental Narrative": "东方叙事香趋势",
}

# This map resolves collisions only. It never assigns a tier to a product that
# appears in a single panel, so the model's original classification is retained
# unless the same SKU was emitted into both price tiers.
BRAND_TIER_RULES = {
    "fenty": "MASSTIGE",
    "make up for ever": "MASSTIGE",
    "ipsa": "LUXURY",
    "ípsa": "LUXURY",
    "茵芙莎": "LUXURY",
    "laura mercier": "LUXURY",
    "萝拉蜜思": "LUXURY",
}

BRAND_CANONICAL = {
    "ípsa": "ipsa",
    "茵芙莎": "ipsa",
    "萝拉蜜思": "laura mercier",
}


def _plain(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def _ascii(value: Any) -> str:
    return (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )


def normalized_aliases(product: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for field in ("name", "name_cn"):
        normalized = "".join(
            char for char in str(product.get(field, "")).casefold() if char.isalnum()
        )
        if normalized:
            aliases.add(normalized)
    return aliases


def _source_url(product: dict[str, Any]) -> str:
    return str(
        ((product.get("detail") or {}).get("price_link") or {}).get("link") or ""
    ).strip().casefold()


def _known_brand(product: dict[str, Any]) -> str:
    detail = product.get("detail") or {}
    blob = " ".join(
        (
            str(product.get("name") or ""),
            str(product.get("name_cn") or ""),
            str((detail.get("brand") or {}).get("en") or ""),
            str((detail.get("brand") or {}).get("cn") or ""),
        )
    ).casefold()
    ascii_blob = _ascii(blob)
    for brand in sorted(BRAND_TIER_RULES, key=len, reverse=True):
        if brand in blob:
            return BRAND_CANONICAL.get(brand, _ascii(brand))
        if _ascii(brand) and _ascii(brand) in ascii_blob:
            return BRAND_CANONICAL.get(brand, _ascii(brand))
    ascii_name = _ascii(product.get("name"))
    match = re.match(r"\s*([a-z0-9][a-z0-9'&.-]{2,})", ascii_name)
    return match.group(1) if match else ""


def _category_family(product: dict[str, Any]) -> str:
    text = _plain(product.get("category_badge")).casefold()
    families = (
        "foundation",
        "cushion",
        "concealer",
        "lipstick",
        "lip gloss",
        "lip balm",
        "lip oil",
        "blush",
        "eyeshadow",
        "mascara",
        "eau de parfum",
        "eau de toilette",
        "hair perfume",
        "fragrance collection",
    )
    return next((family for family in families if family in text), text)


def product_identity_keys(product: dict[str, Any]) -> set[str]:
    keys = {f"name:{alias}" for alias in normalized_aliases(product)}
    source_url = _source_url(product)
    brand = _known_brand(product)
    category = _category_family(product)
    if source_url and brand and category:
        keys.add(f"source:{source_url}|brand:{brand}|category:{category}")
    return keys


def same_product(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if normalized_aliases(left) & normalized_aliases(right):
        return True
    left_brand, right_brand = _known_brand(left), _known_brand(right)
    left_category, right_category = _category_family(left), _category_family(right)
    same_brand_category = (
        bool(left_brand)
        and left_brand == right_brand
        and bool(left_category)
        and left_category == right_category
    )
    if same_brand_category and _source_url(left) and _source_url(left) == _source_url(right):
        return True
    left_name = re.sub(r"[^a-z0-9]+", "", _ascii(left.get("name")))
    right_name = re.sub(r"[^a-z0-9]+", "", _ascii(right.get("name")))
    return bool(
        same_brand_category
        and left_name
        and right_name
        and SequenceMatcher(None, left_name, right_name).ratio() >= 0.68
    )


def _preferred_tier(*products: dict[str, Any]) -> str | None:
    known_brands = {_known_brand(product) for product in products}
    for brand, tier in BRAND_TIER_RULES.items():
        if BRAND_CANONICAL.get(brand, _ascii(brand)) in known_brands:
            return tier
    return None


def _quality(product: dict[str, Any]) -> tuple[int, float]:
    grade = str((product.get("launch_evidence") or {}).get("evidence_grade") or "")
    grade_rank = {"A": 3, "B": 2, "C": 1}.get(grade, 0)
    return grade_rank, float(product.get("score") or 0)


def dedupe_cross_tier_panels(panels: dict[str, list[dict[str, Any]]]) -> None:
    """Remove the same SKU from competing tiers and restore sequential ranks."""
    for market in ("US", "CN"):
        luxury_key = f"{market} LUXURY"
        masstige_key = f"{market} MASSTIGE"
        luxury = list(panels.get(luxury_key, []))
        masstige = list(panels.get(masstige_key, []))
        remove_luxury: set[int] = set()
        remove_masstige: set[int] = set()
        for luxury_index, luxury_product in enumerate(luxury):
            for masstige_index, masstige_product in enumerate(masstige):
                if not same_product(luxury_product, masstige_product):
                    continue
                preferred = _preferred_tier(luxury_product, masstige_product)
                if preferred == "MASSTIGE":
                    remove_luxury.add(luxury_index)
                elif preferred == "LUXURY":
                    remove_masstige.add(masstige_index)
                elif _quality(masstige_product) > _quality(luxury_product):
                    remove_luxury.add(luxury_index)
                else:
                    remove_masstige.add(masstige_index)

        if luxury_key in panels:
            panels[luxury_key] = [
                product for index, product in enumerate(luxury) if index not in remove_luxury
            ]
        if masstige_key in panels:
            panels[masstige_key] = [
                product for index, product in enumerate(masstige) if index not in remove_masstige
            ]
        for tier, key in (("LUXURY", luxury_key), ("MASSTIGE", masstige_key)):
            rows = panels.get(key, [])
            rows.sort(key=lambda product: float(product.get("score") or 0), reverse=True)
            for rank, product in enumerate(rows, 1):
                product["rank"] = rank
                product["market"] = market
                product["tier"] = tier


def _explicit_trend_tag(product: dict[str, Any]) -> str:
    trend = product.get("trend") or {}
    return str(product.get("trend_badge") or trend.get("tag") or "").strip()


def matches_trend(topic: str, trend_name: str, product: dict[str, Any]) -> bool:
    explicit = _explicit_trend_tag(product)
    if explicit == trend_name or (
        explicit == "Trend" and (product.get("trend") or {}).get("tag") == trend_name
    ):
        return True

    detail = product.get("detail") or {}
    name = _plain(f"{product.get('name', '')} {product.get('name_cn', '')}").casefold()
    category = _plain(product.get("category_badge", "")).casefold()
    features = _plain(str((detail.get("key_features") or {}).get("en", ""))).casefold()
    descriptive = _plain(
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
                    "serum", "skincare", "skin care", "hydrating", "moistur", "nourish",
                    "treatment", "peptide", "niacinamide", "ceramide", "hyaluronic", "养肤",
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
                    "balm", "treatment", "hydrating", "moistur", "peptide", "serum",
                    "repair", "nourish", "comfort", "plump", "volumiz", "润唇", "保湿", "修护",
                )
            )
            return lip_product and benefit
        if trend_name == "Low-Saturation Pastel":
            return any(
                cue in full_text
                for cue in (
                    "low-saturation", "low saturation", "pastel", "muted", "macaron", "lilac",
                    "lavender", "powder blue", "pale pink", "马卡龙", "馬卡龍", "低饱和", "低飽和",
                )
            )

    if trend_name == "Milky Musk":
        return any(
            cue in full_text
            for cue in (
                "milky", "milk accord", "lactonic", "mochi milk", "skin scent", "white musk",
                "soft musk", "cashmere musk", "乳感", "白麝香",
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


def group_trend_products(
    topic: str, products: dict[str, Any]
) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {
        name: [] for name in TREND_TAXONOMY[topic]
    }
    seen: dict[str, set[str]] = {name: set() for name in groups}
    for section in ("heat_rankings", "new_product_radar"):
        for panel, rows in products.get(section, {}).items():
            for row in rows:
                identity_keys = product_identity_keys(row)
                if not identity_keys:
                    continue
                for trend_name in groups:
                    if not matches_trend(topic, trend_name, row):
                        continue
                    if identity_keys & seen[trend_name]:
                        continue
                    groups[trend_name].append((panel, row))
                    seen[trend_name].update(identity_keys)
    return groups


def _qualified_new(product: dict[str, Any], month: str) -> bool:
    evidence = product.get("launch_evidence") or {}
    launch_date = str(evidence.get("launch_date") or "")
    nested = evidence.get("evidence") or {}
    return bool(
        evidence.get("quarantine_status") == "verified"
        and launch_date.startswith(f"{month}-")
        and nested.get("url")
    )


def _trend_object(trend_name: str) -> dict[str, str]:
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", trend_name.casefold()).strip("-"),
        "tag": trend_name,
        "tag_cn": TREND_CN[trend_name],
        "rationale": (
            f"Evidence-backed category and feature copy match the {trend_name} taxonomy."
        ),
    }


def apply_product_labels(report: dict[str, Any]) -> None:
    """Restore evidence-backed Trend and New badges without fabricating signals."""
    month = str(report.get("month") or "")
    for topic, topic_data in (report.get("products") or {}).items():
        if topic not in TREND_TAXONOMY or not isinstance(topic_data, dict):
            continue
        radar_by_panel = topic_data.get("new_product_radar") or {}
        qualified_radar: dict[str, list[dict[str, Any]]] = {}
        for panel, rows in radar_by_panel.items():
            qualified_radar[panel] = [row for row in rows if _qualified_new(row, month)]

        for section in ("heat_rankings", "new_product_radar"):
            for panel, rows in (topic_data.get(section) or {}).items():
                for product in rows:
                    existing_trend = product.get("trend") or {}
                    existing_tag = str(existing_trend.get("tag") or "")
                    trend_name = (
                        existing_tag
                        if existing_tag in TREND_TAXONOMY[topic]
                        else next(
                            (
                                trend
                                for trend in TREND_TAXONOMY[topic]
                                if matches_trend(topic, trend, product)
                            ),
                            None,
                        )
                    )
                    if trend_name:
                        canonical_trend = _trend_object(trend_name)
                        if str(existing_trend.get("rationale") or "").strip():
                            canonical_trend["rationale"] = existing_trend["rationale"]
                        product["trend_badge"] = "Trend"
                        product["trend"] = canonical_trend
                    if product.get("new_badge"):
                        continue
                    radar_new = section == "new_product_radar" and _qualified_new(
                        product, month
                    )
                    heat_new = section == "heat_rankings" and any(
                        same_product(product, radar_product)
                        for radar_product in qualified_radar.get(panel, [])
                    )
                    if radar_new or heat_new:
                        product["new_badge"] = "New"


def dedupe_market_observations(report: dict[str, Any]) -> None:
    """Keep observations distinct from every formal product and from each other."""
    formal_by_topic: dict[str, list[dict[str, Any]]] = {}
    for topic, topic_data in (report.get("products") or {}).items():
        formal_by_topic[topic] = [
            product
            for section in ("heat_rankings", "new_product_radar")
            for products in (topic_data.get(section) or {}).values()
            for product in products
        ]

    for topic, panels in (report.get("market_observation") or {}).items():
        if not isinstance(panels, dict):
            continue
        accepted: list[dict[str, Any]] = []
        for panel, products in panels.items():
            unique: list[dict[str, Any]] = []
            for product in products:
                if any(same_product(product, formal) for formal in formal_by_topic.get(topic, [])):
                    continue
                if any(same_product(product, prior) for prior in accepted):
                    continue
                unique.append(product)
                accepted.append(product)
            panels[panel] = unique


def normalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy suitable for validation, scoring, and rendering."""
    normalized = deepcopy(report)
    for topic_data in (normalized.get("products") or {}).values():
        if not isinstance(topic_data, dict):
            continue
        for section in ("heat_rankings", "new_product_radar"):
            panels = topic_data.get(section)
            if isinstance(panels, dict):
                dedupe_cross_tier_panels(panels)
    dedupe_market_observations(normalized)
    apply_product_labels(normalized)
    return normalized
