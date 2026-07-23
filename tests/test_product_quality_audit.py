from build.audit_product_quality import (
    CJK_PATTERN,
    _is_evidence_url,
    _is_explicit_evidence_link,
    _is_generic_url,
    audit_rank_order,
    audit_score_breakdown,
)


def test_rejects_storefront_and_category_urls():
    assert _is_generic_url("https://www.sephora.com")
    assert _is_generic_url("https://flowerknows.tmall.com/")
    assert _is_generic_url("https://example.com/collections")
    assert _is_generic_url("https://example.com/products")
    assert _is_generic_url("https://www.carslan.com.cn/xilie")
    assert _is_generic_url("https://www.yslbeauty.com/int/pure-shot-collection.html")


def test_accepts_product_level_urls():
    assert not _is_generic_url(
        "https://phlur.com/products/missing-person"
    )
    assert not _is_generic_url(
        "https://www.sephora.com/product/le-male-in-blue-limited-edition-P525202"
    )


def test_allows_archive_evidence_url_as_explicit_fallback():
    assert _is_evidence_url(
        "https://github.com/edeleneguo/beauty-weekly/blob/709c63b/archive/week-27/index.html"
    )


def test_allows_explicit_editorial_evidence_link():
    product = {
        "detail": {
            "price_link": {
                "en": "Evidence-backed observed range: ¥129-199",
            }
        },
        "launch_evidence": {
            "evidence": {
                "type": "editorial",
                "url": "https://www.vogue.com.cn/beauty/new-in-store/news_111g3fa47d40aa74.html",
            }
        },
    }
    assert _is_explicit_evidence_link(
        product,
        "https://www.vogue.com.cn/beauty/new-in-store/news_111g3fa47d40aa74.html",
    )


def test_rejects_editorial_link_when_visible_copy_is_not_explicit():
    product = {
        "detail": {
            "price_link": {
                "en": "¥129-199",
            }
        },
        "launch_evidence": {
            "evidence": {
                "type": "editorial",
                "url": "https://www.vogue.com.cn/beauty/new-in-store/news_111g3fa47d40aa74.html",
            }
        },
    }
    assert not _is_explicit_evidence_link(
        product,
        "https://www.vogue.com.cn/beauty/new-in-store/news_111g3fa47d40aa74.html",
    )


def test_cjk_pattern_catches_mixed_visible_copy():
    assert CJK_PATTERN.search("Launch a palette to 切入 spring trends")
    assert not CJK_PATTERN.search("Launch a palette to target spring trends")


def test_rank_order_requires_sequential_descending_scores():
    report = {
        "products": {
            "makeup": {
                "heat_rankings": {
                    "US LUXURY": [
                        {"name": "B", "rank": 2, "score": 90},
                        {"name": "A", "rank": 1, "score": 80},
                    ]
                },
                "new_product_radar": {},
            },
            "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
        }
    }
    errors = audit_rank_order(report)
    assert any("ranks" in error for error in errors)


def test_score_breakdown_requires_weighted_components_and_data_quality():
    report = {
        "products": {
            "makeup": {
                "heat_rankings": {
                    "US LUXURY": [
                        {
                            "name": "A",
                            "rank": 1,
                            "score": 80,
                            "score_breakdown": {
                                "methodology": "Weighted display explanation",
                                "recomputable": False,
                                "total": 80,
                                "components": [
                                    {
                                        "id": "sales_momentum",
                                        "label": "Sales Momentum",
                                        "weight": 0.40,
                                        "max_points": 40,
                                        "points": 32,
                                        "evidence": "Sales proxy",
                                    },
                                    {
                                        "id": "buzz_momentum",
                                        "label": "Buzz Momentum",
                                        "weight": 0.30,
                                        "max_points": 30,
                                        "points": 24,
                                        "evidence": "Buzz proxy",
                                    },
                                    {
                                        "id": "review_rating",
                                        "label": "Review / Rating",
                                        "weight": 0.20,
                                        "max_points": 20,
                                        "points": 16,
                                        "evidence": "Reviews proxy",
                                    },
                                    {
                                        "id": "trend_fit",
                                        "label": "Trend Fit",
                                        "weight": 0.10,
                                        "max_points": 10,
                                        "points": 8,
                                        "evidence": "Trend fit",
                                    },
                                ],
                            },
                            "data_quality": {
                                "source_type": "editorial",
                                "link_type": "editorial_evidence",
                                "coverage_score": 83,
                                "coverage": {
                                    "price": True,
                                    "link": True,
                                    "features": True,
                                    "buzz": True,
                                    "positioning": True,
                                    "launch_evidence": False,
                                },
                                "missing_fields": ["launch_evidence"],
                                "note": "Editorial fallback",
                            },
                        }
                    ]
                },
                "new_product_radar": {},
            },
            "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
        }
    }
    assert audit_score_breakdown(report) == []


def test_score_breakdown_rejects_bad_component_sum():
    report = {
        "products": {
            "makeup": {
                "heat_rankings": {
                    "US LUXURY": [
                        {
                            "name": "A",
                            "rank": 1,
                            "score": 80,
                            "score_breakdown": {
                                "methodology": "Weighted display explanation",
                                "recomputable": False,
                                "total": 80,
                                "components": [
                                    {
                                        "id": "sales_momentum",
                                        "label": "Sales Momentum",
                                        "weight": 0.40,
                                        "max_points": 40,
                                        "points": 40,
                                        "evidence": "Sales proxy",
                                    },
                                    {
                                        "id": "buzz_momentum",
                                        "label": "Buzz Momentum",
                                        "weight": 0.30,
                                        "max_points": 30,
                                        "points": 30,
                                        "evidence": "Buzz proxy",
                                    },
                                    {
                                        "id": "review_rating",
                                        "label": "Review / Rating",
                                        "weight": 0.20,
                                        "max_points": 20,
                                        "points": 20,
                                        "evidence": "Reviews proxy",
                                    },
                                    {
                                        "id": "trend_fit",
                                        "label": "Trend Fit",
                                        "weight": 0.10,
                                        "max_points": 10,
                                        "points": 10,
                                        "evidence": "Trend fit",
                                    },
                                ],
                            },
                            "data_quality": {
                                "source_type": "editorial",
                                "link_type": "editorial_evidence",
                                "coverage_score": 83,
                                "coverage": {
                                    "price": True,
                                    "link": True,
                                    "features": True,
                                    "buzz": True,
                                    "positioning": True,
                                    "launch_evidence": False,
                                },
                                "missing_fields": ["launch_evidence"],
                                "note": "Editorial fallback",
                            },
                        }
                    ]
                },
                "new_product_radar": {},
            },
            "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
        }
    }
    errors = audit_score_breakdown(report)
    assert any("do not sum" in error for error in errors)
