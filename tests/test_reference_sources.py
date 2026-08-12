import contextlib
import json
from pathlib import Path

from build.collect import (
    _dedupe_articles,
    _format_discovery_query,
    _is_cn_new_product_article,
    _is_fragrance_roundup_article,
    _load_cn_discovery_config,
    _load_fragrance_roundup_config,
    _load_main_references,
    _news_search_url,
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
    assert {item["market"] for item in refs} == {"CN", "TW", "US"}
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


def test_reference_registry_has_monthly_fragrance_roundups():
    names = {item["name"] for item in _load_main_references()}
    assert "NewBeauty best new fragrances July" in names
    assert "Scentbird best new perfume releases July" in names
    assert "Vogue Taiwan 7月香氛新品盤點" in names


def test_reference_search_is_bounded_to_target_calendar_month():
    url = _reference_search_url(_load_main_references()[0], "2026-06")
    assert "after%3A2026-06-01" in url
    assert "before%3A2026-07-01" in url


def test_tw_market_news_search_uses_traditional_chinese_locale():
    url = _news_search_url("Vogue Taiwan 香氛新品", "TW", "2026-07")
    assert "hl=zh-TW" in url
    assert "gl=TW" in url
    assert "ceid=TW%3Azh-Hant" in url
    assert "after%3A2026-07-01" in url
    assert "before%3A2026-08-01" in url


def test_tw_reference_search_uses_traditional_chinese_category_terms():
    ref = {"name": "Vogue Taiwan 7月香氛新品盤點", "market": "TW", "type": "Fashion media"}
    url = _reference_search_url(ref, "2026-07")
    assert "hl=zh-TW" in url
    # Traditional-Chinese category terms: 香水 / 香氛 / 美妝 / 保養 / 彩妝
    assert "%E9%A6%99%E6%B0%B4" in url
    assert "%E9%A6%99%E6%B0%9B" in url
    assert "%E7%BE%8E%E5%A6%9D" in url
    assert "after%3A2026-07-01" in url


def test_vogue_taiwan_reference_is_taiwan_market_fragrance_category():
    refs = _load_main_references()
    ref = next(r for r in refs if r["name"] == "Vogue Taiwan 7月香氛新品盤點")
    assert ref["market"] == "TW"
    assert ref.get("category") == "fragrance"


def test_fragrance_roundup_registry_covers_target_outlets_across_markets():
    config = _load_fragrance_roundup_config()
    sources = config["roundup_sources"]
    outlets = {item["outlet"] for item in sources}
    assert "NewBeauty" in outlets
    assert "Vogue Taiwan" in outlets
    assert "Scentbird" in outlets
    assert "T3" in outlets
    assert "Marie Claire" in outlets
    assert "Gap" in outlets
    assert "PRNewswire" in outlets
    assert {item["market"] for item in sources} == {"US", "TW"}
    assert all(item.get("category") == "fragrance" for item in sources)


def test_fragrance_roundup_queries_are_month_templated():
    config = _load_fragrance_roundup_config()
    for item in config["roundup_sources"]:
        rendered = _format_discovery_query(item, "2026-07")
        assert "{year}" not in rendered
        assert "{month_number}" not in rendered
        assert "{month_name}" not in rendered
    tw = next(item for item in config["roundup_sources"] if item["outlet"] == "Vogue Taiwan")
    assert "2026年7月" in _format_discovery_query(tw, "2026-07")


def test_fragrance_roundup_filter_accepts_roundups_and_rejects_unrelated():
    assert _is_fragrance_roundup_article(
        {
            "title": "The Best New Fragrances in July, From Cereal-Inspired Scents",
            "summary": "A roundup of this month's fragrance launches.",
        }
    )
    assert _is_fragrance_roundup_article(
        {
            "title": "7月香氛新品盤點：Tom Ford橙光陶爾米納",
            "summary": "本月香水新品上市",
        }
    )
    assert _is_fragrance_roundup_article(
        {
            "title": (
                "Megan Thee Stallion Enters Fragrance Industry With Hot Girl Summer Eau de Parfum"
            ),
            "summary": "",
        }
    )
    assert not _is_fragrance_roundup_article(
        {
            "title": "旅宿精選｜2026夏季全台飯店住房專案盤點",
            "summary": "飯店住宿推薦",
        }
    )
    assert not _is_fragrance_roundup_article(
        {
            "title": "Olive Young Editor Picks: Moisturizers to Glass Skin",
            "summary": "Top ten must-buy list",
        }
    )


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
        collect._decode_google_news_url("https://news.google.com/rss/articles/encoded?oc=5")
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

    def fake_search(product_name, category, month, market="CN"):
        return (
            {
                "product_name": product_name,
                "category": category,
                "market": market,
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
    generate_weekly._supplement_candidate_evidence(
        generated,
        raw_data,
        "makeup",
        "2026-06",
    )

    assert raw_data["total_articles"] == 1
    assert raw_data["candidate_evidence_audit"][0]["articles_added"] == 1
    assert raw_data["candidate_evidence_audit"][0]["market"] == "CN"
    assert raw_data["articles"][0]["market"] == "CN"


def test_search_product_evidence_us_uses_english_terms_and_tags_candidate(monkeypatch):
    from build import collect

    urls = []

    def fake_fetch(url):
        urls.append(url)
        return (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<rss version='2.0'><channel><item>"
            "<title>Megan Thee Stallion Launches Hot Girl Summer Eau de Parfum</title>"
            "<link>https://news.google.com/rss/articles/encoded?oc=5</link>"
            "<pubDate>Sun, 12 Jul 2026 09:00:00 GMT</pubDate>"
            "</item></channel></rss>"
        )

    monkeypatch.setattr(collect, "fetch_url", fake_fetch)
    monkeypatch.setattr(
        collect,
        "gnewsdecoder",
        lambda url, interval=0: {
            "status": True,
            "decoded_url": "https://publisher.example/news/hot-girl-summer",
        },
    )

    audit, articles = collect.search_product_evidence(
        "Hot Girl Summer Eau de Parfum",
        "fragrance",
        "2026-07",
        market="US",
    )
    search_url = urls[0]
    assert "hl=en-US" in search_url
    assert "gl=US" in search_url
    assert "ceid=US%3Aen" in search_url
    assert "after%3A2026-07-01" in search_url
    assert "before%3A2026-08-01" in search_url
    # English market-language terms drive the US query.
    assert "%22Hot+Girl+Summer+Eau+de+Parfum%22" in search_url
    assert "fragrance+OR+perfume+OR+cologne" in search_url

    assert audit["market"] == "US"
    assert audit["type"] == "candidate_verification"
    assert len(articles) == 1
    assert articles[0]["candidate_name"] == "Hot Girl Summer Eau de Parfum"
    assert articles[0]["reference_type"] == "candidate_verification"
    assert articles[0]["url"] == "https://publisher.example/news/hot-girl-summer"


def test_search_product_evidence_cn_default_keeps_chinese_terms(monkeypatch):
    from build import collect

    urls = []

    def fake_fetch(url):
        urls.append(url)
        return "<rss version='2.0'></rss>"

    monkeypatch.setattr(collect, "fetch_url", fake_fetch)

    audit, articles = collect.search_product_evidence(
        "观夏 昆仑煮雪",
        "fragrance",
        "2026-07",
    )
    search_url = urls[0]
    assert audit["market"] == "CN"
    assert audit["type"] == "candidate_verification"
    assert articles == []
    assert "hl=zh-CN" in search_url
    assert "gl=CN" in search_url
    # Simplified-Chinese market-language terms drive the default CN query.
    assert "%E9%A6%99%E6%B0%B4" in search_url  # 香水
    assert "%E9%A6%99%E6%B0%9B" in search_url  # 香氛
    assert "%E6%96%B0%E5%93%81" in search_url  # 新品


def test_supplement_searches_us_and_cn_fragrance_across_sections(monkeypatch):
    from build import generate_weekly

    raw_data = {"articles": [], "candidate_evidence_audit": []}
    generated = {
        "heat_rankings": {
            "US LUXURY": [
                {
                    "name": "Hot Girl Summer Eau de Parfum",
                    "link": "https://sephora.com/test",
                    "source_url": "https://roundup.example/best-new",
                }
            ]
        },
        "new_product_radar": {
            "US MASSTIGE": [],
            "CN LUXURY": [
                {
                    "name": "闻献 蝶变淡香精",
                    "link": "https://tmall.example/test",
                    "source_url": "https://cn-roundup.example/roundup",
                }
            ],
        },
    }

    searches = []

    def fake_search(product_name, category, month, market="CN"):
        searches.append((product_name, market))
        return (
            {
                "product_name": product_name,
                "category": category,
                "market": market,
                "articles_count": 1,
            },
            [
                {
                    "source": "publisher",
                    "title": f"{product_name} launch",
                    "url": f"https://publisher.example/{market.lower()}/{product_name}",
                    "date": "2026-07-12",
                    "summary": f"{product_name} launch details",
                    "market": market,
                    "reference_type": "candidate_verification",
                    "candidate_name": product_name,
                }
            ],
        )

    monkeypatch.setattr(generate_weekly, "search_product_evidence", fake_search)
    generate_weekly._supplement_candidate_evidence(
        generated,
        raw_data,
        "fragrance",
        "2026-07",
    )

    assert set(searches) == {
        ("Hot Girl Summer Eau de Parfum", "US"),
        ("闻献 蝶变淡香精", "CN"),
    }
    assert len(raw_data["candidate_evidence_audit"]) == 2
    assert all(item["articles_added"] == 1 for item in raw_data["candidate_evidence_audit"])
    assert raw_data["total_articles"] == 2


def test_generation_retries_keep_best_verified_attempt(monkeypatch):
    """A later radar retry must not erase evidence-complete heat panels."""
    from build import generate_weekly

    panels = ["US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"]

    def product(panel, suffix):
        return {
            "name": f"Verified {panel} {suffix}",
            "market": panel.split()[0],
            "tier": panel.split()[1],
            "link": f"https://brand.example/{panel.replace(' ', '-').lower()}-{suffix}",
            "source_url": f"https://publisher.example/{panel.replace(' ', '-').lower()}-{suffix}",
        }

    first = {
        "heat_rankings": {panel: [product(panel, "heat")] for panel in panels},
        "new_product_radar": {panel: [] for panel in panels},
    }
    worse = {
        "heat_rankings": {panel: [] for panel in panels},
        "new_product_radar": {panel: [] for panel in panels},
    }
    responses = iter([first, worse, worse])
    monkeypatch.setattr(generate_weekly, "call_llm", lambda *_: "{}")
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 1)
    monkeypatch.setattr(generate_weekly, "_supplement_candidate_evidence", lambda *_: None)
    monkeypatch.setattr(
        generate_weekly,
        "make_product",
        lambda **kwargs: {
            "name": kwargs["name"],
            "rank": kwargs["rank"],
            "score": kwargs["score"],
            "market": kwargs["market"],
            "tier": kwargs["tier"],
            "launch_evidence": {"launch_date": "2026-07-15", "evidence": {"url": "x"}},
        },
    )
    raw = {
        "articles": [
            {"url": product(panel, "heat")["source_url"], "title": panel, "date": "2026-07-15"}
            for panel in panels
        ]
    }

    result = generate_weekly.generate_products(
        raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
    )
    assert all(result["heat_rankings"][panel] for panel in panels)


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
