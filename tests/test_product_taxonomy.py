from beauty_weekly.product_taxonomy import (
    apply_product_labels,
    dedupe_cross_tier_panels,
    normalize_report,
)


def _evidence(status="verified", launch_date="2026-09-12", grade="A"):
    return {
        "quarantine_status": status,
        "launch_date": launch_date,
        "evidence_grade": grade,
        "evidence": {"url": "https://example.com/launch"},
    }


def _product(
    name,
    category,
    features,
    *,
    market="US",
    tier="LUXURY",
    name_cn="",
    link="https://example.com/product",
    score=80,
    evidence=None,
):
    return {
        "rank": 1,
        "market": market,
        "tier": tier,
        "name": name,
        "name_cn": name_cn,
        "category_badge": category,
        "score": score,
        "detail": {
            "key_features": {"en": features, "cn": features},
            "buzz": {"en": "Editorial coverage", "cn": "Editorial coverage"},
            "brand": {"en": "Brand positioning", "cn": "Brand positioning"},
            "price_link": {"en": "Price unavailable", "cn": "Price unavailable", "link": link},
        },
        "launch_evidence": evidence,
        "trend_badge": None,
        "new_badge": None,
        "trend": None,
    }


def test_dedupe_cross_tier_panels_uses_product_identity_and_brand_tier_rules():
    luxury_fenty = _product(
        "Fenty Beauty Pro Filt'r Fluid Flex Foundation",
        "Foundation",
        "Flexible foundation",
        tier="LUXURY",
        score=92,
    )
    masstige_fenty = _product(
        "Fenty Pro Filt'r Foundation",
        "Foundation",
        "Flexible foundation",
        tier="MASSTIGE",
        score=91,
    )
    luxury_ipsa = _product(
        "IPSA Serum Foundation",
        "Foundation",
        "Serum foundation",
        market="CN",
        tier="LUXURY",
        name_cn="IPSA玻光养肤精华粉底",
        link="https://example.com/ipsa",
    )
    masstige_ipsa = _product(
        "Ípsa玻光养肤精华粉底",
        "Foundation",
        "Serum foundation",
        market="CN",
        tier="MASSTIGE",
        name_cn="茵芙莎玻光养肤精华粉底",
        link="https://example.com/ipsa",
    )
    panels = {
        "US LUXURY": [luxury_fenty],
        "US MASSTIGE": [masstige_fenty],
        "CN LUXURY": [luxury_ipsa],
        "CN MASSTIGE": [masstige_ipsa],
    }

    dedupe_cross_tier_panels(panels)

    assert panels["US LUXURY"] == []
    assert [row["name"] for row in panels["US MASSTIGE"]] == ["Fenty Pro Filt'r Foundation"]
    assert [row["name"] for row in panels["CN LUXURY"]] == ["IPSA Serum Foundation"]
    assert panels["CN MASSTIGE"] == []


def test_apply_product_labels_restores_strict_trend_and_new_badges():
    rose = _product(
        "SW19 5pm Rose Petal",
        "Eau de Parfum",
        "Rose-petal fragrance",
        market="CN",
        tier="MASSTIGE",
        evidence=_evidence(),
    )
    brand_false_positive = _product(
        "Henry Rose Rhu Berry",
        "Fragrance Collection",
        "Editorially covered release; notes were not disclosed",
        tier="MASSTIGE",
        evidence=_evidence(),
    )
    report = {
        "month": "2026-09",
        "products": {
            "fragrance": {
                "heat_rankings": {
                    "CN MASSTIGE": [rose],
                    "US MASSTIGE": [brand_false_positive],
                },
                "new_product_radar": {
                    "CN MASSTIGE": [dict(rose)],
                    "US MASSTIGE": [dict(brand_false_positive)],
                },
            }
        },
    }

    apply_product_labels(report)

    heat_rose = report["products"]["fragrance"]["heat_rankings"]["CN MASSTIGE"][0]
    heat_henry = report["products"]["fragrance"]["heat_rankings"]["US MASSTIGE"][0]
    assert heat_rose["trend_badge"] == "Trend"
    assert heat_rose["trend"]["tag"] == "Rose Revival"
    assert heat_rose["new_badge"] == "New"
    assert heat_henry["trend_badge"] is None
    assert heat_henry["trend"] is None
    assert heat_henry["new_badge"] == "New"


def test_new_badge_requires_verified_launch_inside_report_month():
    out_of_window = _product(
        "Old Launch",
        "Lip Balm",
        "Hydrating balm",
        evidence=_evidence(status="verified", launch_date="2026-08-30"),
    )
    unverified = _product(
        "Unverified Launch",
        "Lip Balm",
        "Hydrating balm",
        evidence=_evidence(status="unverified", launch_date="2026-09-12"),
    )
    report = {
        "month": "2026-09",
        "products": {
            "makeup": {
                "heat_rankings": {"US LUXURY": [out_of_window, unverified]},
                "new_product_radar": {"US LUXURY": [dict(out_of_window), dict(unverified)]},
            }
        },
    }

    apply_product_labels(report)

    for section in ("heat_rankings", "new_product_radar"):
        assert all(
            row["new_badge"] is None
            for row in report["products"]["makeup"][section]["US LUXURY"]
        )


def test_normalize_report_removes_observation_already_present_in_formal_panels():
    formal = _product(
        "Albion Studio Photogenic Soft Focus Emulsion Foundation",
        "Foundation",
        "Soft-focus emulsion foundation",
        market="CN",
        tier="MASSTIGE",
    )
    duplicate_observation = _product(
        "Albion Studio超上镜柔焦乳液粉底",
        "Foundation",
        "Soft-focus emulsion foundation",
        market="CN",
        tier="LUXURY",
        name_cn="Albion Studio超上镜柔焦乳液粉底",
        link="https://example.com/product",
    )
    unique_observation = _product(
        "Tom Ford Architecture Foundation Collection",
        "Foundation",
        "Dimensional complexion collection",
        market="CN",
        tier="LUXURY",
        link="https://example.com/tom-ford",
    )
    report = {
        "month": "2026-09",
        "products": {
            "makeup": {
                "heat_rankings": {"CN MASSTIGE": [formal]},
                "new_product_radar": {},
            }
        },
        "market_observation": {
            "makeup": {"CN LUXURY": [duplicate_observation, unique_observation]}
        },
    }

    normalized = normalize_report(report)

    assert [
        row["name"] for row in normalized["market_observation"]["makeup"]["CN LUXURY"]
    ] == ["Tom Ford Architecture Foundation Collection"]


def test_existing_trend_object_is_normalized_to_canonical_localized_pair():
    product = _product(
        "Example Serum Foundation",
        "Foundation",
        "Skincare serum foundation with niacinamide",
    )
    product["trend_badge"] = "Trend"
    product["trend"] = {
        "id": "skincare-foundation",
        "tag": "Skincare Foundation",
        "tag_cn": "养肤底妆",
        "rationale": "Specific existing rationale.",
    }
    report = {
        "month": "2026-09",
        "products": {
            "makeup": {
                "heat_rankings": {"US LUXURY": [product]},
                "new_product_radar": {},
            }
        },
    }

    apply_product_labels(report)

    trend = report["products"]["makeup"]["heat_rankings"]["US LUXURY"][0]["trend"]
    assert trend["tag_cn"] == "养肤底妆趋势"
    assert trend["rationale"] == "Specific existing rationale."
