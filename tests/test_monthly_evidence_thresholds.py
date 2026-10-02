# ruff: noqa: E501
"""Regression tests for monthly evidence filtering and coverage thresholds.

(a) _find_supporting_articles receives topic/category and rejects articles
    without category relevance; product-link match alone cannot qualify
    unless product name evidence also matches.
(b) Heat coverage thresholds target=10, warning=8, hard minimum=5;
    generation retries below 8 and final result raises below 5.
(c) Radar target minimum 5 with coverage warning metadata.
"""

from __future__ import annotations


def test_into_you_does_not_match_antitrust_investigation():
    from build.generate_monthly import _find_supporting_articles

    articles = [
        {
            "date": "Wed, 26 Aug 2026 13:17:25 +0000",
            "market": "GLOBAL",
            "reference_type": "fragrance",
            "source": "now_smell_this",
            "summary": "Global fragrance makers Givaudan, Firmenich and International Flavors &#38; Fragrances face a second antitrust investigation by Indian authorities, according to a regulatory document seen by Reuters. The latest case relates to alleged price collusion since 2024, said a source close to the matter, and follows an ongoing investigation into accusations that the companies struck labour [&#8230;]",
            "title": "A second antitrust investigation",
            "url": "https://nstperfume.com/2026/08/26/a-second-antitrust-investigation/",
        }
    ]
    result = _find_supporting_articles(
        "INTO YOU x TUNEE GOODS Shero Super Matte Lip & Cheek Mud",
        "https://intoyoucosmetics.com/products/shero-super-matte-lip-cheek-mud",
        articles,
        topic="makeup",
    )
    assert result == []


def test_into_you_rejected_via_category_alias():
    from build.generate_monthly import _find_supporting_articles

    articles = [
        {
            "title": "A second antitrust investigation",
            "summary": "Global fragrance makers face a second antitrust investigation into accusations",
            "url": "https://nstperfume.com/2026/08/26/a-second-antitrust-investigation/",
            "date": "2026-08-26",
            "reference_type": "fragrance",
        }
    ]
    result = _find_supporting_articles(
        "INTO YOU x TUNEE GOODS Shero Super Matte Lip & Cheek Mud",
        "https://intoyoucosmetics.com/products/shero-super-matte-lip-cheek-mud",
        articles,
        category="makeup",
    )
    assert result == []


def test_product_link_alone_does_not_qualify():
    from build.generate_monthly import _find_supporting_articles

    articles = [
        {
            "title": "Sephora product page roundup",
            "url": "https://sephora.com/product/test-item",
            "date": "2026-07-20",
        }
    ]
    result = _find_supporting_articles(
        "Unknown Product",
        "https://sephora.com/product/test-item",
        articles,
        topic="makeup",
    )
    assert result == []


def test_product_link_with_name_qualifies():
    from build.generate_monthly import _find_supporting_articles

    articles = [
        {
            "title": "Rare Beauty Blush launch details",
            "summary": "Rare Beauty Blush official launch",
            "url": "https://sephora.com/product/rare-beauty-blush",
            "date": "2026-07-20",
            "reference_type": "Retailer",
        }
    ]
    result = _find_supporting_articles(
        "Rare Beauty Blush",
        "https://sephora.com/product/rare-beauty-blush",
        articles,
        topic="makeup",
    )
    assert len(result) == 1


def test_substring_false_positive_rejected():
    """'matte' in 'matter' must not count as a token match."""
    from build.generate_monthly import _find_supporting_articles

    articles = [
        {
            "title": "A second antitrust investigation",
            "summary": "said a source close to the matter and follows an investigation into accusations",
            "url": "https://example.com/antitrust",
            "date": "2026-08-26",
        }
    ]
    result = _find_supporting_articles(
        "INTO YOU Shero Super Matte Lip Mud",
        "https://brand.example/mud",
        articles,
        topic="makeup",
    )
    assert result == []


def test_heat_threshold_constants():
    from build import generate_monthly as gm

    assert gm.HEAT_COVERAGE_TARGET == 10
    assert gm.HEAT_COVERAGE_WARNING == 8
    assert gm.HEAT_COVERAGE_MINIMUM == 5
    assert gm.RADAR_COVERAGE_TARGET == 5


def test_generation_retries_below_warning(monkeypatch):
    """Heat panels below 8 per panel must trigger supplemental retry."""
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

    thin = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(7)] for panel in panels
        },
        "new_product_radar": {
            panel: [product(panel, f"radar-{i}") for i in range(5)] for panel in panels
        },
    }
    full = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(10)] for panel in panels
        },
        "new_product_radar": {
            panel: [product(panel, f"radar-{i}") for i in range(5)] for panel in panels
        },
    }
    responses = iter([thin, full])
    calls = {"n": 0}

    def fake_llm(*_args, **_kwargs):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(generate_weekly, "call_llm", fake_llm)
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 0)
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
    raw = {"articles": []}
    result = generate_weekly.generate_products(
        raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
    )
    for panel in panels:
        assert len(result["heat_rankings"][panel]) >= 8
    assert calls["n"] >= 2


def test_generation_raises_below_minimum(monkeypatch):
    """A required heat panel below 5 per panel must raise (hard failure)."""
    import pytest
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

    thin = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(4)] for panel in panels
        },
        "new_product_radar": {panel: [] for panel in panels},
    }
    responses = iter([thin, thin, thin])
    monkeypatch.setattr(generate_weekly, "call_llm", lambda *_: "{}")
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 0)
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
    raw = {"articles": []}
    with pytest.raises(ValueError, match="below hard minimum"):
        generate_weekly.generate_products(
            raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
        )


def test_radar_target_records_warning_metadata():
    from build.generate_monthly import _record_heat_radar_coverage

    raw_data: dict = {}
    result = {
        "heat_rankings": {
            "US LUXURY": [{"name": f"h{i}"} for i in range(10)],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        },
        "new_product_radar": {
            "US LUXURY": [{"name": "r1"}],
            "US MASSTIGE": [{"name": "r2"}],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        },
    }
    _record_heat_radar_coverage(raw_data, "makeup", result)
    health = raw_data["coverage_health"]["makeup"]
    assert health["radar_target"] == 5
    assert health["radar_total"] == 2
    assert health["radar_status"] == "below_target"
    assert health["heat_target"] == 10
    assert health["heat_warning"] == 8
    assert health["heat_minimum"] == 5


def test_per_panel_threshold_constants():
    from build import generate_monthly as gm

    assert gm.HEAT_PANEL_TARGET == 10
    assert gm.HEAT_PANEL_WARNING == 8
    assert gm.HEAT_PANEL_MINIMUM == 5
    assert gm.RADAR_PANEL_TARGET_MIN == 5
    assert gm.RADAR_PANEL_TARGET_MAX == 10


def test_heat_yellow_band_publishes_with_warning(monkeypatch):
    """8-9 formal products per heat panel publish (yellow warning, no raise)."""
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

    steady = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(9)] for panel in panels
        },
        "new_product_radar": {
            panel: [product(panel, f"radar-{i}") for i in range(5)] for panel in panels
        },
    }
    responses = iter([steady, steady, steady])
    monkeypatch.setattr(generate_weekly, "call_llm", lambda *_: "{}")
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 0)
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
    raw: dict = {}
    result = generate_weekly.generate_products(
        raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
    )
    for panel in panels:
        assert len(result["heat_rankings"][panel]) == 9


def test_radar_below_minimum_warns_without_padding(monkeypatch):
    """Radar panels below 5 per panel warn via metadata; never padded."""
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

    data = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(10)] for panel in panels
        },
        "new_product_radar": {
            panel: [product(panel, f"radar-{i}") for i in range(2)] for panel in panels
        },
    }
    responses = iter([data, data, data])
    monkeypatch.setattr(generate_weekly, "call_llm", lambda *_: "{}")
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 0)
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
    raw: dict = {}
    result = generate_weekly.generate_products(
        raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
    )
    for panel in panels:
        assert len(result["new_product_radar"][panel]) == 2
    coverage = (raw.get("panel_coverage") or {}).get("makeup", {}).get("new_product_radar", {})
    assert coverage["US LUXURY"]["status"] == "below_target"
    assert coverage["US LUXURY"]["formal_included_count"] == 2


def test_evidence_tier_routing_c_to_observation(monkeypatch):
    """C-grade social signals route only to market_observation, never formal."""
    from build import generate_weekly

    panels = ["US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"]

    def product(panel, suffix, social=False):
        name = f"Social Buzz {panel} {suffix}" if social else f"Verified {panel} {suffix}"
        slug = name.lower().replace(" ", "-")
        return {
            "name": name,
            "market": panel.split()[0],
            "tier": panel.split()[1],
            "link": f"https://brand.example/{slug}",
            "source_url": f"https://publisher.example/{slug}",
        }

    def fake_make_product(**kwargs):
        grade = "C" if kwargs["name"].startswith("Social Buzz") else "A"
        ev_type = "social_media" if grade == "C" else "launch_announcement"
        return {
            "name": kwargs["name"],
            "rank": kwargs["rank"],
            "score": kwargs["score"],
            "market": kwargs["market"],
            "tier": kwargs["tier"],
            "launch_evidence": {
                "launch_date": "2026-07-15",
                "evidence_grade": grade,
                "evidence": {"url": "https://publisher.example/x", "type": ev_type},
            },
        }

    heat = {}
    for panel in panels:
        items = [product(panel, f"formal-{i}") for i in range(8)]
        items += [product(panel, f"social-{i}", social=True) for i in range(2)]
        heat[panel] = items
    radar = {panel: [product(panel, f"radar-{i}") for i in range(5)] for panel in panels}
    data = {"heat_rankings": heat, "new_product_radar": radar}
    responses = iter([data, data, data])
    monkeypatch.setattr(generate_weekly, "call_llm", lambda *_: "{}")
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 0)
    monkeypatch.setattr(generate_weekly, "_supplement_candidate_evidence", lambda *_: None)
    monkeypatch.setattr(generate_weekly, "make_product", fake_make_product)
    raw: dict = {}
    result = generate_weekly.generate_products(
        raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
    )
    formal_names = {
        p["name"] for panel_products in result["heat_rankings"].values() for p in panel_products
    }
    obs_names = {
        p["name"]
        for panel_products in result["market_observation"].values()
        for p in panel_products
    }
    assert not any(n.startswith("Social Buzz") for n in formal_names)
    assert any(n.startswith("Social Buzz") for n in obs_names)
    for panel_products in result["market_observation"].values():
        for p in panel_products:
            assert p.get("observation_status") == "pending official confirmation"
    from build.generate_monthly import validate_tier_routing as _validate_tier_routing

    assert _validate_tier_routing(result) == []


def test_per_panel_coverage_metadata_fields(monkeypatch):
    """panel_coverage entries carry candidate/verified/formal/observation counts."""
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

    data = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(10)] for panel in panels
        },
        "new_product_radar": {
            panel: [product(panel, f"radar-{i}") for i in range(5)] for panel in panels
        },
    }
    responses = iter([data])
    monkeypatch.setattr(generate_weekly, "call_llm", lambda *_: "{}")
    monkeypatch.setattr(generate_weekly, "parse_json_response", lambda *_: next(responses))
    monkeypatch.setattr(generate_weekly, "_cn_radar_soft_floor", lambda *_: 0)
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
    raw: dict = {}
    generate_weekly.generate_products(
        raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
    )
    heat_meta = (raw.get("panel_coverage") or {}).get("makeup", {}).get("heat_rankings", {})
    entry = heat_meta["US LUXURY"]
    assert entry["candidate_count"] == 10
    assert entry["verified_count"] == 10
    assert entry["formal_included_count"] == 10
    assert entry["observation_count"] == 0
    assert entry["status"] == "met"


def test_render_coverage_note_and_observation():
    from build.render import _render_coverage_note, _render_market_observation

    yellow = _render_coverage_note("en", "heat", 9)
    assert "yellow" in yellow.lower()
    assert "coverage warning" in yellow.lower()
    radar_note = _render_coverage_note("en", "radar", 2)
    assert "transparent coverage warning" in radar_note.lower()
    obs_html = _render_market_observation(
        "makeup",
        "en",
        {
            "US LUXURY": [
                {"name": "KOL Signal Serum", "observation_status": "pending official confirmation"}
            ]
        },
    )
    assert "Market Observation" in obs_html
    assert "pending official confirmation" in obs_html
    assert "observation-item" in obs_html


def test_validate_panel_thresholds_hard_failure():
    from build.generate_monthly import validate_panel_thresholds, validate_tier_routing

    result = {
        "heat_rankings": {
            "US LUXURY": [{"name": f"h{i}"} for i in range(10)],
            "US MASSTIGE": [{"name": f"h{i}"} for i in range(4)],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        },
        "new_product_radar": {},
    }
    errors = validate_panel_thresholds(result)
    assert any("hard minimum" in e for e in errors)
    bad = {
        "heat_rankings": {
            "US LUXURY": [
                {
                    "name": "KOL pick",
                    "launch_evidence": {"evidence_grade": "C"},
                }
            ]
        },
        "new_product_radar": {},
    }
    assert validate_tier_routing(bad) != []


def test_collection_status_card_shows_counts_and_why():
    from build.render import _render_collection_status_card

    entry = {
        "candidate_count": 8,
        "verified_count": 6,
        "formal_included_count": 5,
        "observation_count": 1,
        "status": "below_target",
    }
    html = _render_collection_status_card("en", "heat", "CN LUXURY", 5, entry)
    assert "coverage-status-card" in html
    assert "CN LUXURY" in html
    assert "5/10" in html
    assert "Candidates 8" in html
    assert "Verified 6" in html
    assert "Included 5" in html
    assert "Market Observation" in html
    assert "heat-item" not in html


def test_collection_status_card_met_panel_renders_nothing():
    from build.render import _render_collection_status_card

    entry = {
        "candidate_count": 10,
        "verified_count": 10,
        "formal_included_count": 10,
        "observation_count": 0,
        "status": "met",
    }
    assert _render_collection_status_card("en", "heat", "US LUXURY", 10, entry) == ""


def test_empty_panel_renders_status_card_not_blank():
    from build.render import _render_section

    coverage = {
        "CN LUXURY": {
            "candidate_count": 0,
            "verified_count": 0,
            "formal_included_count": 0,
            "observation_count": 0,
            "status": "below_minimum",
        }
    }
    html = _render_section({"CN LUXURY": []}, "en", "makeup", "heat", coverage)
    assert "coverage-status-card" in html
    assert "0/10" in html


def test_report_carries_panel_coverage():
    import json

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

    data = {
        "heat_rankings": {
            panel: [product(panel, f"heat-{i}") for i in range(10)] for panel in panels
        },
        "new_product_radar": {
            panel: [product(panel, f"radar-{i}") for i in range(5)] for panel in panels
        },
    }
    responses = iter([data])
    import unittest.mock as mock

    with mock.patch.object(generate_weekly, "call_llm", return_value="{}"), mock.patch.object(
        generate_weekly, "parse_json_response", side_effect=lambda *_: next(responses)
    ), mock.patch.object(generate_weekly, "_cn_radar_soft_floor", return_value=0), mock.patch.object(
        generate_weekly, "_supplement_candidate_evidence", return_value=None
    ), mock.patch.object(
        generate_weekly,
        "make_product",
        side_effect=lambda **kwargs: {
            "name": kwargs["name"],
            "rank": kwargs["rank"],
            "score": kwargs["score"],
            "market": kwargs["market"],
            "tier": kwargs["tier"],
            "launch_evidence": {"launch_date": "2026-07-15", "evidence": {"url": "x"}},
        },
    ):
        raw: dict = {"articles": []}
        result = generate_weekly.generate_products(
            raw, "makeup", "2026-07", "Jul 1 – Jul 31, 2026", "2026-08-01T00:00:00Z"
        )
    assert set(result) >= {"heat_rankings", "new_product_radar", "market_observation"}
    entry = raw["panel_coverage"]["makeup"]["heat_rankings"]["US LUXURY"]
    assert entry["formal_included_count"] == 10
    assert entry["status"] == "met"
    json.dumps(raw["panel_coverage"])


def test_canonical_source_urls_include_market_observation_products():
    from beauty_weekly.canonical import _report_source_urls

    observation_url = "https://publisher.example/observed-launch"
    report = {
        "products": {
            "makeup": {"heat_rankings": {}, "new_product_radar": {}},
            "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
        },
        "market_observation": {
            "makeup": {
                "CN MASSTIGE": [
                    {
                        "detail": {"price_link": {"link": observation_url}},
                        "launch_evidence": {"evidence": {"url": observation_url}},
                    }
                ]
            },
            "fragrance": {},
        },
    }

    assert _report_source_urls(report) == {observation_url}


def test_evidence_integrity_counts_market_observation_references():
    from beauty_weekly.evidence import validate_source_product_referential_integrity

    observation_url = "https://publisher.example/observed-launch"
    report = {
        "products": {
            "makeup": {"heat_rankings": {}, "new_product_radar": {}},
            "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
        },
        "market_observation": {
            "makeup": {
                "CN MASSTIGE": [
                    {
                        "name": "Observed Product",
                        "detail": {"price_link": {"link": observation_url}},
                        "launch_evidence": {"evidence": {"url": observation_url}},
                    }
                ]
            },
            "fragrance": {},
        },
    }
    sources = {"sources": [{"url": observation_url}]}

    assert validate_source_product_referential_integrity(report, sources) == []

    from beauty_weekly.validate_published import (
        validate_product_source_referential_integrity,
        validate_source_citation,
    )

    assert validate_product_source_referential_integrity(report, sources) == []
    assert validate_source_citation(report, sources) == []
