from beauty_weekly.product_taxonomy import (
    apply_market_tier_policy,
    apply_product_labels,
    dedupe_cross_tier_panels,
    normalize_report,
    refined_category_badge,
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


def test_market_tier_policy_keeps_cn_luxury_global_and_cn_masstige_domestic_only():
    panels = {
        "US LUXURY": [
            _product("Prada Soft Blur Blush", "Blush", "Soft blur", score=94),
            _product("Armani Silk Foundation", "Foundation", "Silk finish", score=92),
        ],
        "US MASSTIGE": [],
        "CN LUXURY": [
            _product(
                "Tom Ford Architecture Foundation",
                "Foundation",
                "Luxury complexion",
                market="CN",
                score=91,
            )
        ],
        "CN MASSTIGE": [
            _product(
                "Florasis West Lake Fragrance",
                "Eau de Parfum",
                "Domestic fragrance",
                market="CN",
                tier="MASSTIGE",
                score=89,
            ),
            _product(
                "Fenty Gloss Bomb",
                "Lip Gloss",
                "International brand",
                market="CN",
                tier="MASSTIGE",
                score=88,
            ),
        ],
    }

    apply_market_tier_policy(panels, limit=10)

    assert [row["name"] for row in panels["US LUXURY"]] == ["Armani Silk Foundation"]
    assert [row["name"] for row in panels["US MASSTIGE"]] == ["Prada Soft Blur Blush"]
    assert [row["name"] for row in panels["CN LUXURY"]] == [
        "Tom Ford Architecture Foundation"
    ]
    assert [row["name"] for row in panels["CN MASSTIGE"]] == [
        "Florasis West Lake Fragrance"
    ]


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


def test_heat_new_badge_uses_its_own_verified_launch_evidence():
    launch = _product(
        "Verified Heat Launch",
        "Lip Balm",
        "Hydrating balm",
        evidence=_evidence(status="verified", launch_date="2026-09-12"),
    )
    report = {
        "month": "2026-09",
        "products": {
            "makeup": {
                "heat_rankings": {"US LUXURY": [launch]},
                "new_product_radar": {},
            }
        },
    }

    apply_product_labels(report)

    assert launch["new_badge"] == "New"


def test_normalize_report_removes_observation_already_present_in_formal_panels():
    formal = _product(
        "Florasis West Lake Fragrance Series",
        "Foundation",
        "Soft-focus emulsion foundation",
        market="CN",
        tier="MASSTIGE",
    )
    duplicate_observation = _product(
        "Florasis West Lake Fragrance Series",
        "Foundation",
        "Soft-focus emulsion foundation",
        market="CN",
        tier="LUXURY",
        name_cn="花西子西湖情境系列香水",
        link="https://example.com/product",
    )
    duplicate_observation["launch_evidence"] = _evidence(grade="C")
    unique_observation = _product(
        "Tom Ford Architecture Foundation Collection",
        "Foundation",
        "Dimensional complexion collection",
        market="CN",
        tier="LUXURY",
        link="https://example.com/tom-ford",
    )
    unique_observation["launch_evidence"] = _evidence(grade="C")
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


def test_observation_area_keeps_only_c_grade_signals():
    grade_a = _product(
        "Verified Launch",
        "Foundation",
        "Verified serum foundation",
        evidence=_evidence(grade="A"),
    )
    grade_c = _product(
        "Social Signal",
        "Foundation",
        "Unconfirmed serum foundation",
        link="https://example.com/social",
        evidence=_evidence(grade="C"),
    )
    report = {
        "month": "2026-09",
        "products": {"makeup": {"heat_rankings": {}, "new_product_radar": {}}},
        "market_observation": {"makeup": {"US LUXURY": [grade_a, grade_c]}},
    }

    normalized = normalize_report(report)

    assert [
        row["name"]
        for row in normalized["market_observation"]["makeup"]["US LUXURY"]
    ] == ["Social Signal"]


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


def test_makeup_category_badges_are_refined_to_second_level_formats():
    blush = _product(
        "Prada Touch Soft Blur Blush",
        "Blush",
        "Cream-to-powder texture with a soft-blur finish",
    )
    lip = _product(
        "Dior Addict Glass Lipstick",
        "Lipstick",
        "Hydrating glass-like shine",
    )
    serum = _product(
        "IPSA Serum Foundation",
        "Foundation",
        "Serum-infused complexion formula",
    )

    assert refined_category_badge("makeup", blush) == "Cream-to-Powder Blush"
    assert refined_category_badge("makeup", lip) == "Hydrating Glass Lipstick"
    assert refined_category_badge("makeup", serum) == "Skincare Serum Foundation"


def test_normalize_report_removes_repeated_missing_sales_boilerplate():
    product = _product(
        "Example Blush",
        "Blush",
        "Liquid blush",
    )
    product["detail"]["buzz"]["en"] = (
        "Featured in a September editor review; public sales metrics were not disclosed"
    )
    report = {
        "month": "2026-09",
        "products": {
            "makeup": {
                "heat_rankings": {"US LUXURY": [product]},
                "new_product_radar": {},
            }
        },
    }

    normalized = normalize_report(report)

    buzz = normalized["products"]["makeup"]["heat_rankings"]["US LUXURY"][0][
        "detail"
    ]["buzz"]["en"]
    assert buzz == "Featured in a September editor review"


def test_same_sku_keeps_one_category_across_heat_and_radar():
    heat = _product(
        "Fenty Pro Filt'r Foundation",
        "Foundation",
        "Flexible skin-adapting wear",
    )
    radar = _product(
        "Fenty Pro Filt'r Foundation",
        "Foundation",
        "Updated soft-matte foundation finish",
    )
    report = {
        "month": "2026-09",
        "products": {
            "makeup": {
                "heat_rankings": {"US MASSTIGE": [heat]},
                "new_product_radar": {"US MASSTIGE": [radar]},
            }
        },
    }

    normalized = normalize_report(report)
    heat_badge = normalized["products"]["makeup"]["heat_rankings"]["US MASSTIGE"][0][
        "category_badge"
    ]
    radar_badge = normalized["products"]["makeup"]["new_product_radar"]["US MASSTIGE"][0][
        "category_badge"
    ]
    assert heat_badge == radar_badge == "Soft-Matte Foundation"
