from build.audit_product_quality import (
    CJK_PATTERN,
    _is_evidence_url,
    _is_explicit_evidence_link,
    _is_generic_url,
    audit_rank_order,
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
