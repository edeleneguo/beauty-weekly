"""Tests for pre-publish validation and evidence-backed generation.

Covers:
  1. validate_published: launch evidence non-null checks
  2. validate_published: evidence completeness (url, title, published_at, etc.)
  3. validate_published: evidence supported_fields validation
  4. validate_published: evidence type validation
  5. validate_published: product/source referential integrity
  6. validate_published: panel count constraints
  7. validate_published: section count constraints
  8. validate_published: score range constraints
  9. validate_published: bilingual parity (Chinese coverage scope)
 10. validate_published: source citation checks
 11. validate_published: combined pre-publish validation
 12. generate_weekly: _find_supporting_articles matching logic
 13. generate_weekly: _make_launch_evidence fail-closed on missing articles
 14. generate_weekly: _make_launch_evidence with real article
 15. generate_weekly: _build_scoring_json required fields
 16. generate_weekly: _build_manifest required fields
 17. build/validate_published.py CLI script exits
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.validate_published import (  # noqa: E402
    validate_bilingual_parity,
    validate_evidence_completeness,
    validate_evidence_types,
    validate_launch_evidence_non_null,
    validate_panel_counts,
    validate_product_source_referential_integrity,
    validate_score_range,
    validate_section_count,
    validate_source_citation,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

_MISSING = object()


def _make_evidence(
    url: str = "https://elle.com/article/test",
    title: str = "Test Article",
    published_at: str = "2026-07-20T00:00:00Z",
    fetched_at: str = "2026-07-22T00:00:00Z",
    checked_at: str = "2026-07-22T00:00:00Z",
    supported_fields: object = _MISSING,
    ev_type: str = "editorial",
) -> dict:
    if supported_fields is _MISSING:
        supported_fields = ["price", "features", "buzz", "brand", "category", "link"]
    return {
        "url": url,
        "title": title,
        "type": ev_type,
        "published_at": published_at,
        "fetched_at": fetched_at,
        "checked_at": checked_at,
        "supported_fields": supported_fields,
    }


def _make_product(
    name: str = "Test Product",
    score: int = 85,
    link: str = "https://sephora.com/product/test",
    launch_evidence: object = _MISSING,
) -> dict:
    if launch_evidence is _MISSING:
        launch_evidence = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": _make_evidence(url=link),
            "absence_markers": [],
        }
    return {
        "name": name,
        "rank": 1,
        "score": score,
        "market": "US",
        "tier": "LUXURY",
        "category_badge": "Fragrance",
        "detail": {
            "price_link": {"cn": "$100", "en": "$100", "link": link},
            "key_features": {"cn": "test", "en": "test"},
            "buzz": {"cn": "test", "en": "test"},
            "brand": {"cn": "test", "en": "test"},
        },
        "launch_evidence": launch_evidence,
        "trend_badge": None,
        "new_badge": None,
    }


def _make_report(
    heat: dict[str, list[dict]] | None = None,
    radar: dict[str, list[dict]] | None = None,
) -> dict:
    all_panels = {"US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"}
    if heat is None:
        heat = {
            "US LUXURY": [_make_product()],
            "US MASSTIGE": [_make_product(name="P2")],
            "CN LUXURY": [_make_product(name="P3", link="https://tmall.com/test")],
            "CN MASSTIGE": [_make_product(name="P4", link="https://tmall.com/test2")],
        }
    if radar is None:
        radar = {k: [] for k in all_panels}
    # Fragrance heat must also have products (heat min=1)
    frag_heat = {
        "US LUXURY": [_make_product(name="F1", link="https://tmall.com/f1")],
        "US MASSTIGE": [_make_product(name="F2", link="https://tmall.com/f2")],
        "CN LUXURY": [_make_product(name="F3", link="https://tmall.com/f3")],
        "CN MASSTIGE": [_make_product(name="F4", link="https://tmall.com/f4")],
    }
    frag_radar = {k: [] for k in all_panels}
    return {
        "week": 30,
        "date_range": "Jul 20 - Jul 26, 2026",
        "date_range_cn": "7月20日 - 7月26日",
        "version": "week30-2026202607-v1",
        "products": {
            "makeup": {"heat_rankings": heat, "new_product_radar": radar},
            "fragrance": {
                "heat_rankings": frag_heat,
                "new_product_radar": frag_radar,
            },
        },
    }


def _report_with_fragrance(
    heat: dict[str, list[dict]],
    radar: dict[str, list[dict]] | None = None,
) -> dict:
    """Report with custom makeup heat AND populated fragrance panels."""
    all_panels = {"US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"}
    if radar is None:
        radar = {k: [] for k in all_panels}
    frag_heat = {
        "US LUXURY": [_make_product(name="F1", link="https://tmall.com/f1")],
        "US MASSTIGE": [_make_product(name="F2", link="https://tmall.com/f2")],
        "CN LUXURY": [_make_product(name="F3", link="https://tmall.com/f3")],
        "CN MASSTIGE": [_make_product(name="F4", link="https://tmall.com/f4")],
    }
    frag_radar = {k: [] for k in all_panels}
    return {
        "week": 30,
        "date_range": "Jul 20 - Jul 26, 2026",
        "date_range_cn": "7月20日 - 7月26日",
        "version": "week30-2026202607-v1",
        "products": {
            "makeup": {"heat_rankings": heat, "new_product_radar": radar},
            "fragrance": {
                "heat_rankings": frag_heat,
                "new_product_radar": frag_radar,
            },
        },
    }


def _make_sources(urls: list[str] | None = None) -> dict:
    if urls is None:
        urls = [
            "https://sephora.com/product/test",
            "https://sephora.com/product/test2",
            "https://tmall.com/test",
            "https://tmall.com/test2",
        ]
    sources = [
        {
            "id": f"src_{i:04d}",
            "url": url,
            "type": "product_page",
            "checked_at": "2026-07-22T00:00:00Z",
            "provenance": {"verification_status": "verified", "reason": None},
        }
        for i, url in enumerate(urls, 1)
    ]
    return {
        "version": "2.0.0",
        "schema_version": "2.0.0",
        "total_sources": len(sources),
        "sources": sources,
        "provenance": {
            "phase": 7,
            "migration_recorded_at": "2026-07-22T00:00:00Z",
            "evidence_absences": [],
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Launch evidence non-null checks
# ══════════════════════════════════════════════════════════════════════════════


class TestLaunchEvidenceNonNull:
    def test_real_product_passes(self):
        report = _make_report()
        errors = validate_launch_evidence_non_null(report)
        assert errors == []

    def test_null_evidence_detected(self):
        product = _make_product(launch_evidence=None)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_launch_evidence_non_null(report)
        assert len(errors) == 1
        assert "null launch_evidence" in errors[0]

    def test_score_zero_product_skipped(self):
        product = _make_product(score=0, launch_evidence=None)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_launch_evidence_non_null(report)
        assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. Evidence completeness
# ══════════════════════════════════════════════════════════════════════════════


class TestEvidenceCompleteness:
    def test_full_evidence_passes(self):
        report = _make_report()
        errors = validate_evidence_completeness(report)
        assert errors == []

    def test_missing_url_detected(self):
        ev = _make_evidence(url="")
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": ev,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert any("evidence.url is empty" in e for e in errors)

    def test_missing_title_detected(self):
        ev = _make_evidence(title="")
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": ev,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert any("evidence.title is empty" in e for e in errors)

    def test_missing_published_at_detected(self):
        ev = _make_evidence(published_at="")
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": ev,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert any("evidence.published_at is empty" in e for e in errors)

    def test_empty_supported_fields_detected(self):
        ev = _make_evidence(supported_fields=[])
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": ev,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert any("supported_fields is empty" in e for e in errors)

    def test_absence_markers_ok(self):
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "unverified",
            "evidence": None,
            "absence_markers": [{"reason": "No URL", "gap_type": "no_url"}],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert errors == []

    def test_no_evidence_no_absence_detected(self):
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "unverified",
            "evidence": None,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert any("no evidence and no absence_markers" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Evidence supported_fields validation
# ══════════════════════════════════════════════════════════════════════════════


class TestEvidenceSupportedFields:
    def test_valid_fields_pass(self):
        report = _make_report()
        errors = validate_evidence_completeness(report)
        assert errors == []

    def test_invalid_field_detected(self):
        ev = _make_evidence(supported_fields=["price", "bogus_field"])
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": ev,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_completeness(report)
        assert any("unsupported field 'bogus_field'" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Evidence type validation
# ══════════════════════════════════════════════════════════════════════════════


class TestEvidenceTypes:
    def test_valid_type_passes(self):
        report = _make_report()
        errors = validate_evidence_types(report)
        assert errors == []

    def test_invalid_type_detected(self):
        ev = _make_evidence(ev_type="bogus_type")
        le = {
            "launch_date": "2026-W30",
            "quarantine_status": "verified",
            "evidence": ev,
            "absence_markers": [],
        }
        product = _make_product(launch_evidence=le)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_evidence_types(report)
        assert any("bogus_type" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Product/source referential integrity
# ══════════════════════════════════════════════════════════════════════════════


class TestProductSourceIntegrity:
    def test_matching_urls_pass(self):
        report = _make_report()
        # Default report: P1=test, P2=test, P3=tmall/test, P4=tmall/test2
        # F1-F4 = tmall/f1-f4; evidence URLs == product links
        sources = _make_sources(
            [
                "https://sephora.com/product/test",
                "https://tmall.com/test",
                "https://tmall.com/test2",
                "https://tmall.com/f1",
                "https://tmall.com/f2",
                "https://tmall.com/f3",
                "https://tmall.com/f4",
            ]
        )
        errors = validate_product_source_referential_integrity(report, sources)
        assert errors == []

    def test_missing_source_detected(self):
        heat = {
            "US LUXURY": [_make_product(link="https://missing.com/x")],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        sources = _make_sources([])
        errors = validate_product_source_referential_integrity(report, sources)
        assert any("not in sources.json" in e for e in errors)

    def test_orphaned_source_detected(self):
        report = _make_report()
        sources = _make_sources(
            [
                "https://sephora.com/product/test",
                "https://tmall.com/test",
                "https://tmall.com/test2",
                "https://tmall.com/f1",
                "https://tmall.com/f2",
                "https://tmall.com/f3",
                "https://tmall.com/f4",
                "https://orphan.example.com",
            ]
        )
        errors = validate_product_source_referential_integrity(report, sources)
        assert any("not referenced" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Panel count constraints
# ══════════════════════════════════════════════════════════════════════════════


class TestPanelCounts:
    def test_valid_counts_pass(self):
        report = _make_report()
        errors = validate_panel_counts(report)
        assert errors == []

    def test_heat_panel_over_limit_detected(self):
        products = [_make_product(name=f"P{i}", score=85) for i in range(11)]
        heat = {
            "US LUXURY": products,
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_panel_counts(report)
        assert any("11 products" in e for e in errors)

    def test_heat_panel_under_limit_detected(self):
        heat = {
            "US LUXURY": [],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_panel_counts(report)
        assert any("0 products" in e for e in errors)

    def test_missing_panel_detected(self):
        heat = {
            "US LUXURY": [_make_product()],
            "US MASSTIGE": [_make_product(name="P2")],
            "CN LUXURY": [_make_product(name="P3", link="https://tmall.com/x")],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_panel_counts(report)
        assert any("missing panels" in e for e in errors)

    def test_radar_panel_over_limit_detected(self):
        radar_products = [_make_product(name=f"R{i}", score=85) for i in range(11)]
        radar = {
            "US LUXURY": radar_products,
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _make_report(radar=radar)
        errors = validate_panel_counts(report)
        assert any("11 products" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Section count constraints
# ══════════════════════════════════════════════════════════════════════════════


class TestSectionCounts:
    def test_valid_sections_pass(self):
        report = _make_report()
        errors = validate_section_count(report)
        assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# 8. Score range constraints
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreRange:
    def test_valid_scores_pass(self):
        report = _make_report()
        errors = validate_score_range(report)
        assert errors == []

    def test_score_below_minimum_detected(self):
        product = _make_product(score=50)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_score_range(report)
        assert any("out of range" in e for e in errors)

    def test_score_above_maximum_detected(self):
        product = _make_product(score=99)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_score_range(report)
        assert any("out of range" in e for e in errors)

    def test_score_zero_skipped(self):
        product = _make_product(score=0)
        heat = {
            "US LUXURY": [product],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_score_range(report)
        assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# 9. Bilingual parity
# ══════════════════════════════════════════════════════════════════════════════


class TestBilingualParity:
    def test_both_panels_populated_passes(self):
        report = _make_report()
        errors = validate_bilingual_parity(report)
        assert errors == []

    def test_us_only_detected(self):
        heat = {
            "US LUXURY": [_make_product()],
            "US MASSTIGE": [_make_product(name="P2")],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_bilingual_parity(report)
        assert any("0 CN products" in e for e in errors)

    def test_cn_only_not_flagged(self):
        heat = {
            "US LUXURY": [],
            "US MASSTIGE": [],
            "CN LUXURY": [_make_product(name="CN1", link="https://tmall.com/x")],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_bilingual_parity(report)
        assert errors == []

    def test_empty_both_not_flagged(self):
        heat = {
            "US LUXURY": [],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        errors = validate_bilingual_parity(report)
        assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# 10. Source citation checks
# ══════════════════════════════════════════════════════════════════════════════


class TestSourceCitation:
    def test_cited_urls_pass(self):
        report = _make_report()
        sources = _make_sources(
            [
                "https://sephora.com/product/test",
                "https://tmall.com/test",
                "https://tmall.com/test2",
                "https://tmall.com/f1",
                "https://tmall.com/f2",
                "https://tmall.com/f3",
                "https://tmall.com/f4",
            ]
        )
        errors = validate_source_citation(report, sources)
        assert errors == []

    def test_uncited_url_detected(self):
        heat = {
            "US LUXURY": [_make_product(link="https://missing.com/x")],
            "US MASSTIGE": [],
            "CN LUXURY": [],
            "CN MASSTIGE": [],
        }
        report = _report_with_fragrance(heat=heat)
        sources = _make_sources([])
        errors = validate_source_citation(report, sources)
        assert any("not in sources.json" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 11. Generate_weekly helper functions
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateWeeklyHelpers:
    def test_find_supporting_articles_by_name(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Best Rare Beauty Blush Review",
                "url": "https://elle.com/review",
                "date": "2026-07-20",
            },
            {
                "title": "Hair Trends for Summer",
                "url": "https://elle.com/hair",
                "date": "2026-07-19",
            },
        ]
        result = _find_supporting_articles(
            "Rare Beauty Blush", "https://sephora.com/test", articles
        )
        assert len(result) == 1
        assert "Rare Beauty" in result[0]["title"]

    def test_find_supporting_articles_by_url(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Sephora product page roundup",
                "url": "https://sephora.com/product/test",
                "date": "2026-07-20",
            },
        ]
        result = _find_supporting_articles(
            "Unknown Product", "https://sephora.com/product/test", articles
        )
        assert len(result) == 1

    def test_find_supporting_articles_none_found(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Unrelated Article",
                "url": "https://elle.com/unrelated",
                "date": "2026-07-20",
            },
        ]
        result = _find_supporting_articles(
            "Completely Different Product", "https://other.com/x", articles
        )
        assert len(result) == 0

    def test_find_supporting_articles_by_summary(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Best Summer Beauty Trends",
                "url": "https://elle.com/trends",
                "date": "2026-07-20",
                "summary": "Rare Beauty Blush is taking over social media this season",
            },
            {
                "title": "Hair Trends for Summer",
                "url": "https://elle.com/hair",
                "date": "2026-07-19",
            },
        ]
        result = _find_supporting_articles(
            "Rare Beauty Blush", "https://sephora.com/test", articles
        )
        assert len(result) == 1
        assert result[0]["url"] == "https://elle.com/trends"

    def test_find_supporting_articles_unrelated_fails(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Best Summer Beauty Trends",
                "url": "https://elle.com/trends",
                "date": "2026-07-20",
                "summary": "Everything you need to know about skincare",
            },
        ]
        result = _find_supporting_articles(
            "Rare Beauty Blush", "https://sephora.com/test", articles
        )
        assert len(result) == 0

    def test_find_supporting_articles_single_token_not_enough(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Color Trends for Summer",
                "url": "https://elle.com/color",
                "date": "2026-07-20",
                "summary": "Bright hues are in this season",
            },
        ]
        result = _find_supporting_articles("Color Wow", "https://sephora.com/test", articles)
        assert len(result) == 0

    def test_find_supporting_articles_unrelated_source_url_rejected(self):
        """source_url alone must NOT qualify as evidence without name match."""
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Unrelated Title No Match",
                "url": "https://elle.com/exact-article",
                "date": "2026-07-20",
                "summary": "Some content",
            },
        ]
        result = _find_supporting_articles(
            "Mystery Product",
            "https://sephora.com/test",
            articles,
            source_url="https://elle.com/exact-article",
        )
        assert len(result) == 0

    def test_make_launch_evidence_with_article(self):
        from build.generate_weekly import _make_launch_evidence

        articles = [
            {
                "title": "Product A - Best New Launch of 2026",
                "url": "https://elle.com/sale",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
            },
        ]
        result = _make_launch_evidence(
            "Product A",
            "https://sephora.com/test",
            "makeup",
            "2026-W30",
            "2026-07-22T00:00:00Z",
            articles,
        )
        assert result["quarantine_status"] == "verified"
        assert result["evidence"] is not None
        assert result["evidence"]["url"] == "https://elle.com/sale"
        assert result["evidence"]["title"] == "Product A - Best New Launch of 2026"

    def test_make_launch_evidence_fails_without_articles(self):
        from build.generate_weekly import _make_launch_evidence

        with pytest.raises(ValueError, match="no source articles support it"):
            _make_launch_evidence(
                "Product B",
                "https://sephora.com/test",
                "makeup",
                "2026-W30",
                "2026-07-22T00:00:00Z",
                [],
            )

    def test_build_scoring_json_has_required_fields(self):
        from build.generate_weekly import _build_scoring_json

        report = _make_report()
        scoring = _build_scoring_json(report, "2026-07-22T00:00:00Z")
        assert "version" in scoring
        assert "observed_statistics" in scoring
        assert "validation_rules" in scoring
        assert "known_constraints" in scoring
        assert "products" in scoring
        assert "recomputable" in scoring
        assert "scoring_formula" in scoring

    def test_build_manifest_has_required_fields(self):
        from build.generate_weekly import _build_manifest

        report_json = '{"test": true}'
        sources_json = '{"sources": []}'
        scoring_json = '{"version": "1.0.0"}'
        manifest = _build_manifest(
            report_json,
            sources_json,
            scoring_json,
            "2026-W30",
            30,
            "Jul 20 - Jul 26, 2026",
            "7月20日 - 7月26日",
            "2026-07-22T00:00:00Z",
        )
        for field in (
            "canonical_hash",
            "scoring_hash",
            "sources_hash",
            "domain_separation",
            "legacy_fields_isolated",
            "migration_deprecation",
            "migration_gaps",
            "schema_version",
            "resolved_warnings",
            "remaining_warnings",
        ):
            assert field in manifest, f"manifest missing '{field}'"


# ══════════════════════════════════════════════════════════════════════════════
# 12. build/validate_published.py CLI script
# ══════════════════════════════════════════════════════════════════════════════


class TestValidatePublishedScript:
    def test_script_importable(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from beauty_weekly.validate_published import validate_for_publish",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, f"Import failed:\n{result.stderr}"
