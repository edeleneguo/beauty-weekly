from build.render import _group_trend_products, _render_trends


def _product(
    name,
    category,
    features,
    *,
    name_cn="",
    trend_badge=None,
    brand="",
    buzz="",
    link="",
):
    return {
        "name": name,
        "name_cn": name_cn,
        "category_badge": category,
        "trend_badge": trend_badge,
        "detail": {
            "key_features": {"en": features},
            "buzz": {"en": buzz},
            "brand": {"en": brand},
            "price_link": {"en": "", "link": link},
        },
    }


def test_trend_grouping_uses_strict_semantic_evidence():
    products = {
        "heat_rankings": {
            "CN LUXURY": [
                _product("IPSA Serum Foundation", "Foundation", "Serum-infused skincare formula"),
                _product("Dior Forever Matte", "Foundation", "Soft matte complexion finish"),
                _product("Armani Cheek Tint", "Blush", "Macaron-inspired shades"),
                _product("Dior Glass Lipstick", "Lipstick", "Hydrating lip feel"),
            ]
        },
        "new_product_radar": {},
    }

    groups = _group_trend_products("makeup", products)

    assert [row[1]["name"] for row in groups["Skincare Foundation"]] == [
        "IPSA Serum Foundation"
    ]
    assert [row[1]["name"] for row in groups["Functional Lip"]] == [
        "Dior Glass Lipstick"
    ]
    assert [row[1]["name"] for row in groups["Low-Saturation Pastel"]] == [
        "Armani Cheek Tint"
    ]


def test_fragrance_trends_do_not_equate_tea_with_matcha_or_vanilla_with_milk():
    products = {
        "heat_rankings": {
            "CN MASSTIGE": [
                _product("Kuoca Black Tea", "Eau de Parfum", "Black-tea concept"),
                _product("SW19 5pm Rose Petal", "Eau de Parfum", "Rose-petal theme"),
            ],
            "US MASSTIGE": [
                _product("Phlur Vanilla Canyon", "Fragrance", "Vanilla concept"),
                _product("Temple Oud", "Hair Perfume", "Temple oud scent"),
            ],
        },
        "new_product_radar": {},
    }

    groups = _group_trend_products("fragrance", products)

    assert groups["Matcha Fragrance"] == []
    assert groups["Milky Musk"] == []
    assert [row[1]["name"] for row in groups["Rose Revival"]] == [
        "SW19 5pm Rose Petal"
    ]
    assert [row[1]["name"] for row in groups["Oriental Narrative"]] == ["Temple Oud"]


def test_fragrance_brand_name_does_not_trigger_rose_trend():
    products = {
        "heat_rankings": {
            "US MASSTIGE": [
                _product(
                    "Henry Rose Rhu Berry",
                    "Fragrance Collection",
                    "A new fragrance release receiving editorial attention",
                    brand="Modern American fragrance brand",
                    buzz="Henry Rose Rhu Berry was included in an editorial ranking",
                )
            ]
        },
        "new_product_radar": {},
    }

    groups = _group_trend_products("fragrance", products)

    assert groups["Rose Revival"] == []


def test_trend_grouping_counts_same_sku_once_across_sections_and_aliases():
    shared = _product(
        "Fenty Gloss Bomb",
        "Lip Gloss",
        "Hydrating glossy lip formula",
        name_cn="FENTY星尘流光唇釉",
    )
    localized = _product(
        "FENTY星尘流光唇釉",
        "Lip Gloss",
        "Hydrating glossy lip formula",
        name_cn="FENTY星尘流光唇釉",
    )
    products = {
        "heat_rankings": {"CN LUXURY": [shared], "CN MASSTIGE": [localized]},
        "new_product_radar": {"CN LUXURY": [shared]},
    }

    groups = _group_trend_products("makeup", products)

    assert len(groups["Functional Lip"]) == 1


def test_trend_grouping_deduplicates_localized_names_from_same_source():
    source = "https://example.com/september-launches"
    english = _product(
        "IPSA Serum Foundation",
        "Foundation",
        "Serum-infused complexion formula",
        name_cn="IPSA玻光养肤精华粉底",
        link=source,
    )
    localized = _product(
        "Ípsa玻光养肤精华粉底",
        "Foundation",
        "Serum foundation with skincare positioning",
        name_cn="茵芙莎玻光养肤精华粉底",
        link=source,
    )
    products = {
        "heat_rankings": {"CN LUXURY": [english], "CN MASSTIGE": [localized]},
        "new_product_radar": {},
    }

    groups = _group_trend_products("makeup", products)

    assert len(groups["Skincare Foundation"]) == 1


def test_trend_rendering_uses_singular_signal_and_labels_names_as_examples():
    products = {
        "heat_rankings": {
            "CN LUXURY": [
                _product("SW19 5pm Rose Petal", "Eau de Parfum", "Rose-petal theme")
            ]
        },
        "new_product_radar": {},
    }

    rendered = _render_trends("fragrance", products, "September 2026")

    assert "1 evidence-backed product signal" in rendered
    assert "product signals" not in rendered
    assert "Examples: SW19 5pm Rose Petal" in rendered
