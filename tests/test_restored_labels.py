from pathlib import Path

from build.enrich_dashboard_metrics import (
    prune_unreferenced_sources,
    repair_market_observation_evidence,
)
from build.render import _render_news, _render_trends

ROOT = Path(__file__).resolve().parent.parent


def _trend_product(name, market, tier, score, grade):
    return {
        "name": name,
        "name_cn": "",
        "market": market,
        "tier": tier,
        "score": score,
        "category_badge": "Lip Balm",
        "trend_badge": "Trend",
        "trend": {
            "id": "functional-lip",
            "tag": "Functional Lip",
            "tag_cn": "功效型唇妆",
            "rationale": "Evidence-backed taxonomy match.",
        },
        "launch_evidence": {"evidence_grade": grade},
        "detail": {
            "key_features": {"en": "Hydrating lip balm"},
            "buzz": {"en": "Editorial coverage"},
            "brand": {"en": "Beauty brand"},
            "price_link": {"en": "Price unavailable", "link": "https://example.com"},
        },
    }


def test_trend_cards_restore_market_evidence_and_decision_labels():
    products = {
        "heat_rankings": {
            "CN MASSTIGE": [_trend_product("CN Balm", "CN", "MASSTIGE", 88, "A")],
            "US LUXURY": [_trend_product("US Balm", "US", "LUXURY", 84, "B")],
        },
        "new_product_radar": {},
    }

    rendered = _render_trends("makeup", products, "September 2026")

    assert 'class="region-tag cn"' in rendered
    assert 'class="region-tag us"' in rendered
    assert rendered.count('class="signal-chip') == 2
    assert "Evidence A" in rendered
    assert "Evidence B" in rendered
    assert 'class="dec-label">Decision rule' in rendered
    assert 'class="dec-signal">Functional Lip' in rendered


def test_news_cards_restore_type_label_and_show_actual_publisher():
    article = {
        "title": "Brand launches a new serum foundation",
        "summary": "A verified September launch.",
        "url": "https://www.glam.com/example",
        "market": "US",
        "source": "YouTube beauty products",
        "reference_type": "Social video",
        "date": "2026-09-12",
    }

    rendered = _render_news("makeup", [article], "September 2026")

    assert 'class="news-card-tag event">Launch' in rendered
    assert "Source: Glam" in rendered
    assert "YouTube beauty products" not in rendered


def test_templates_use_current_weighted_methodology_only():
    for page in ("index.html", "fragrance.html"):
        text = (ROOT / "templates" / "pages" / page).read_text(encoding="utf-8")
        assert "Sales Momentum (40%)" in text
        assert "Buzz Momentum (30%)" in text
        assert "Review / Rating (20%)" in text
        assert "Trend Fit (10%)" in text
        assert "MVP stage uses 50/50" not in text
        assert "Sales Score (&le;50) + Buzz Score (&le;50)" not in text


def test_market_observation_evidence_is_rebound_to_its_explicit_source():
    cited_url = "https://publisher.example/september-launches"
    report = {
        "month": "2026-09",
        "market_observation": {
            "makeup": {
                "CN LUXURY": [
                    {
                        "name": "Example Serum Foundation",
                        "name_cn": "",
                        "detail": {"price_link": {"link": cited_url}},
                        "launch_evidence": {
                            "evidence_grade": "C",
                            "evidence": {"url": "https://wrong.example/unrelated"},
                        },
                    }
                ]
            }
        },
    }
    articles = [
        {
            "title": "September launches: Example Serum Foundation",
            "summary": "Example Serum Foundation is included in the roundup.",
            "url": cited_url,
            "date": "2026-09-10",
            "category": "makeup",
            "reference_type": "makeup_new_product_discovery",
        },
        {
            "title": "Later Example foundation story",
            "summary": "Example Serum Foundation is mentioned in passing.",
            "url": "https://other.example/later-story",
            "date": "2026-09-29",
            "category": "makeup",
            "reference_type": "editorial",
        },
    ]

    repair_market_observation_evidence(report, articles)

    evidence = report["market_observation"]["makeup"]["CN LUXURY"][0][
        "launch_evidence"
    ]
    assert evidence["evidence"]["url"] == cited_url
    assert evidence["launch_date"] == "2026-09-10"


def test_source_registry_drops_only_urls_orphaned_by_normalization():
    used = "https://publisher.example/used"
    report = {
        "products": {
            "makeup": {
                "heat_rankings": {
                    "US LUXURY": [
                        {
                            "detail": {"price_link": {"link": used}},
                            "launch_evidence": {"evidence": {"url": used}},
                        }
                    ]
                },
                "new_product_radar": {},
            }
        },
        "market_observation": {},
    }
    sources = {
        "sources": [
            {"id": "src_1", "url": used},
            {"id": "src_2", "url": "https://publisher.example/orphan"},
        ]
    }

    prune_unreferenced_sources(report, sources)

    assert sources["sources"] == [{"id": "src_1", "url": used}]
