import contextlib
import json
from pathlib import Path

from build.collect import (
    _dedupe_articles,
    _format_discovery_query,
    _is_cn_new_product_article,
    _load_cn_discovery_config,
    _load_main_references,
    _reference_search_url,
)
from build.generate_weekly import generate_products

ROOT = Path(__file__).resolve().parent.parent


def test_reference_policy_is_mandatory_but_not_whitelist():
    data = json.loads((ROOT / "config" / "reference_sources.json").read_text())
    assert "Every source is searched" in data["policy"]["main_reference_semantics"]
    assert "not a whitelist" in data["policy"]["main_reference_semantics"]
    assert "Other valid public sources" in data["policy"]["additional_source_semantics"]


def test_reference_registry_covers_both_markets_and_named_sources():
    refs = _load_main_references()
    names = {item["name"] for item in refs}
    assert {item["market"] for item in refs} == {"CN", "US"}
    for expected in (
        "天猫新品创新中心 (TMIC)",
        "魔镜洞察",
        "飞瓜数据",
        "小红书 美妆 新品",
        "闻献 DOCUMENTS",
        "完美日记",
        "Sephora new beauty",
        "WGSN beauty trends",
        "Circana prestige beauty",
        "Fragrantica new perfumes",
    ):
        assert expected in names


def test_every_reference_has_a_search_url():
    for reference in _load_main_references():
        url = _reference_search_url(reference)
        assert url.startswith("https://news.google.com/rss/search?")
        assert "q=" in url


def test_reference_search_is_bounded_to_target_calendar_month():
    url = _reference_search_url(_load_main_references()[0], "2026-06")
    assert "after%3A2026-06-01" in url
    assert "before%3A2026-07-01" in url


def test_cn_new_product_registry_has_category_queries_and_soft_floors():
    config = _load_cn_discovery_config()
    assert config["soft_floor"] == {"makeup": 8, "fragrance": 4}
    assert len(config["discovery_queries"]["makeup"]) >= 4
    assert len(config["discovery_queries"]["fragrance"]) >= 4
    assert any("香水" in item["query"] for item in config["discovery_queries"]["fragrance"])
    assert any("彩妆" in item["query"] for item in config["discovery_queries"]["makeup"])
    monthly_query = next(
        item
        for item in config["discovery_queries"]["makeup"]
        if item["name"] == "CN monthly makeup roundups"
    )
    assert "2026年6月" in _format_discovery_query(monthly_query, "2026-06")


def test_collection_deduplicates_articles_by_url():
    articles = [
        {"url": "https://example.com/a", "title": "first"},
        {"url": "https://example.com/a", "title": "duplicate"},
        {"url": "https://example.com/b", "title": "second"},
    ]
    assert [item["title"] for item in _dedupe_articles(articles)] == ["first", "second"]


def test_google_news_url_is_decoded_to_direct_source(monkeypatch):
    from build import collect

    monkeypatch.setattr(
        collect,
        "gnewsdecoder",
        lambda url, interval=0: {
            "status": True,
            "decoded_url": "https://publisher.example/launch",
        },
    )
    assert (
        collect._decode_google_news_url(
            "https://news.google.com/rss/articles/encoded?oc=5"
        )
        == "https://publisher.example/launch"
    )


def test_metadata_parser_extracts_structured_description():
    from build.collect import _MetadataParser

    parser = _MetadataParser()
    parser.feed(
        '<html><head><meta property="og:description" '
        'content="Official product launch details"></head></html>'
    )
    assert parser.description == "Official product launch details"


def test_cn_fragrance_discovery_rejects_beverage_false_positive():
    article = {
        "title": "香水柠檬新品上市",
        "summary": "全新夏季饮料首发",
    }
    assert not _is_cn_new_product_article(article, "fragrance")


def test_cn_fragrance_discovery_accepts_real_launch():
    article = {
        "title": "品牌全新木质香水正式发布",
        "summary": "新品香氛本月上市",
    }
    assert _is_cn_new_product_article(article, "fragrance")


def test_cn_makeup_discovery_requires_product_and_launch_cues():
    assert _is_cn_new_product_article(
        {"title": "全新气垫粉底上市", "summary": "彩妆新品"},
        "makeup",
    )
    assert not _is_cn_new_product_article(
        {"title": "美妆行业月度报告", "summary": "市场规模增长"},
        "makeup",
    )
    assert not _is_cn_new_product_article(
        {"title": "汽车高光版正式上市", "summary": "新车型发布"},
        "makeup",
    )


def test_candidate_specific_search_is_saved_in_raw_audit(monkeypatch):
    from build import generate_weekly

    raw_data = {"articles": [], "candidate_evidence_audit": []}
    generated = {
        "new_product_radar": {
            "CN LUXURY": [
                {
                    "name": "Example China Lipstick",
                    "link": "https://brand.example/products/lipstick",
                    "source_url": "",
                }
            ]
        }
    }

    def fake_search(product_name, category, month):
        return (
            {
                "product_name": product_name,
                "category": category,
                "articles_count": 1,
            },
            [
                {
                    "source": "Brand official",
                    "title": "Example China Lipstick 新品发布",
                    "url": "https://brand.example/news/lipstick-launch",
                    "date": "2026-06-12",
                    "summary": "Example China Lipstick 正式上市",
                    "market": "CN",
                    "reference_type": "Brand official",
                }
            ],
        )

    monkeypatch.setattr(generate_weekly, "search_product_evidence", fake_search)
    generate_weekly._supplement_cn_radar_evidence(
        generated,
        raw_data,
        "makeup",
        "2026-06",
    )

    assert raw_data["total_articles"] == 1
    assert raw_data["candidate_evidence_audit"][0]["articles_added"] == 1
    assert raw_data["articles"][0]["market"] == "CN"


def test_official_cn_launch_receives_grade_a():
    from build.generate_weekly import _make_launch_evidence

    evidence = _make_launch_evidence(
        "Example China Lipstick",
        "https://brand.example/products/lipstick",
        "makeup",
        "2026-06",
        "2026-07-01T01:00:00Z",
        [
            {
                "source": "Example Brand",
                "title": "Example China Lipstick 新品发布",
                "url": "https://brand.example/news/lipstick-launch",
                "date": "2026-06-12",
                "summary": "Example China Lipstick 正式上市",
                "market": "CN",
                "reference_type": "Brand official",
                "source_authority": "official",
            }
        ],
    )

    assert evidence["evidence_grade"] == "A"
    assert evidence["date_basis"] == "official_launch"
    assert evidence["launch_date"] == "2026-06-12"


def test_cn_radar_soft_floor_records_health_without_padding():
    from build.generate_weekly import _record_cn_radar_coverage

    raw_data = {}
    result = {
        "new_product_radar": {
            "US LUXURY": [{"name": "US item"}],
            "CN LUXURY": [{"name": "CN item"}],
            "CN MASSTIGE": [],
        }
    }
    _record_cn_radar_coverage(raw_data, "fragrance", result, 4)
    health = raw_data["coverage_health"]["fragrance"]
    assert health["verified_count"] == 1
    assert health["soft_floor"] == 4
    assert health["status"] == "below_soft_floor"


def test_brand_category_metadata_boosts_relevance():
    from build.generate_weekly import _score_article_relevance

    generic_brand_event = {
        "title": "品牌新品鉴赏会",
        "summary": "",
        "category": "fragrance",
    }
    assert _score_article_relevance(generic_brand_event, "fragrance") >= 10
    assert _score_article_relevance(generic_brand_event, "makeup") == 0


def test_generation_prompt_uses_bounded_balanced_evidence(monkeypatch):
    articles = []
    for market in ("CN", "US"):
        for index in range(100):
            articles.append(
                {
                    "source": f"{market}-{index}",
                    "title": f"{market} Product {index}",
                    "url": f"https://example.org/{market.lower()}/{index}",
                    "date": "2026-07-22",
                    "summary": "x" * 500,
                    "market": market,
                }
            )

    captured = {}

    def fake_call_llm(system_prompt, user_prompt, max_tokens=8000):
        captured.setdefault("user_prompt", user_prompt)
        return '{"heat_rankings": {}, "new_product_radar": {}}'

    monkeypatch.setattr("build.generate_weekly.call_llm", fake_call_llm)
    with contextlib.suppress(ValueError):
        generate_products(
            {"articles": articles},
            "makeup",
            "2026-W30",
            "Jul 20 – Jul 26, 2026",
            "2026-07-22T00:00:00Z",
        )

    prompt = captured["user_prompt"]
    assert prompt.count("(URL:") == 30
    assert "CN Product 14" in prompt
    assert "US Product 14" in prompt
    assert "CN Product 15" not in prompt
    assert len(prompt.encode("utf-8")) < 20_000
