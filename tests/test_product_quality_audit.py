from build.audit_product_quality import CJK_PATTERN, _is_generic_url


def test_rejects_storefront_and_category_urls():
    assert _is_generic_url("https://www.sephora.com")
    assert _is_generic_url("https://flowerknows.tmall.com/")
    assert _is_generic_url("https://example.com/collections")
    assert _is_generic_url("https://example.com/products")


def test_accepts_product_level_urls():
    assert not _is_generic_url(
        "https://phlur.com/products/missing-person"
    )
    assert not _is_generic_url(
        "https://www.sephora.com/product/le-male-in-blue-limited-edition-P525202"
    )


def test_cjk_pattern_catches_mixed_visible_copy():
    assert CJK_PATTERN.search("Launch a palette to 切入 spring trends")
    assert not CJK_PATTERN.search("Launch a palette to target spring trends")
