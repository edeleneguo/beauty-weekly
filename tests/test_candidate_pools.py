from __future__ import annotations

from beauty_weekly.candidates import build_evidence_pool, panel_candidates
from build.generate_monthly import _resolve_candidate_source


def article(
    index: int,
    *,
    market: str = "US",
    title: str | None = None,
    url: str | None = None,
    authority: str = "editorial",
) -> dict:
    return {
        "title": title or f"Brand {index} launches lipstick shade {index}",
        "summary": f"A verified makeup launch with product details for shade {index}.",
        "url": url or f"https://publisher.example/products/lipstick-{index}",
        "market": market,
        "source_authority": authority,
        "date": "2026-09-15",
    }


def test_pool_considers_all_relevant_articles_not_a_thirty_article_slice():
    articles = [article(index) for index in range(75)]

    pool = build_evidence_pool(articles, "makeup", "2026-09")

    assert len(pool) == 75
    assert pool[-1].title == "Brand 74 launches lipstick shade 74"


def test_pool_deduplicates_urls_and_preserves_exact_evidence():
    duplicate_url = "https://publisher.example/products/lipstick-one"
    articles = [
        article(1, url=duplicate_url),
        article(2, url=duplicate_url, title="Syndicated copy of lipstick one"),
    ]

    pool = build_evidence_pool(articles, "makeup", "2026-09")

    assert len(pool) == 1
    assert pool[0].url == duplicate_url
    assert pool[0].excerpt.startswith("A verified makeup launch")
    assert pool[0].candidate_id.startswith("src_")


def test_pool_rejects_cross_category_noise():
    articles = [
        article(1, title="Brand launches velvet lipstick"),
        article(2, title="Brand launches oud eau de parfum"),
        article(3, title="The best new perfumes of September"),
    ]

    pool = build_evidence_pool(articles, "makeup", "2026-09")

    assert [candidate.title for candidate in pool] == ["Brand launches velvet lipstick"]


def test_panel_candidates_partition_market_and_keep_unknown_tier_available():
    articles = [
        article(1, market="CN", title="Luxury Dior lipstick launch"),
        article(2, market="US", title="Affordable e.l.f. mascara launch"),
        article(3, market="US", title="Independent brand blush launch"),
    ]
    pool = build_evidence_pool(articles, "makeup", "2026-09")

    assert [c.title for c in panel_candidates(pool, "CN LUXURY")] == [
        "Luxury Dior lipstick launch"
    ]
    assert [c.title for c in panel_candidates(pool, "US MASSTIGE")] == [
        "Affordable e.l.f. mascara launch",
        "Independent brand blush launch",
    ]


def test_greater_china_sources_feed_cn_panels():
    pool = build_evidence_pool(
        [article(1, market="TW", title="9月彩妆新品盘点：Armani腮红")],
        "makeup",
        "2026-09",
    )

    assert panel_candidates(pool, "CN LUXURY")[0].market == "CN"
    assert panel_candidates(pool, "US LUXURY") == []


def test_product_roundups_are_prioritized_and_available_to_both_tiers():
    generic = article(1, title="Fall makeup trend report")
    roundup = article(2, title="The Best New Makeup Launches for September")
    roundup["product_mentions"] = ["Chanel Lipstick", "Kiko Milano Mattifier"]
    roundup["summary"] = "Products named in article: Chanel Lipstick; Kiko Milano Mattifier"

    pool = build_evidence_pool([generic, roundup], "makeup", "2026-09")

    assert pool[0].title == roundup["title"]
    assert panel_candidates(pool, "US LUXURY")[0] == pool[0]
    assert pool[0] in panel_candidates(pool, "US MASSTIGE")


def test_official_sources_rank_before_editorial_sources():
    articles = [article(1), article(2, authority="official")]

    pool = build_evidence_pool(articles, "makeup", "2026-09")

    assert pool[0].title == "Brand 2 launches lipstick shade 2"


def test_model_source_id_resolves_to_exact_collected_url():
    pool = build_evidence_pool([article(1)], "makeup", "2026-09")
    source_map = {candidate.candidate_id: candidate.url for candidate in pool}

    assert _resolve_candidate_source(
        {"source_id": pool[0].candidate_id, "source_url": "https://invented.invalid"},
        source_map,
        set(source_map.values()),
    ) == pool[0].url
    assert (
        _resolve_candidate_source(
            {"source_id": "unknown", "source_url": "https://invented.invalid"},
            source_map,
            set(source_map.values()),
        )
        is None
    )
