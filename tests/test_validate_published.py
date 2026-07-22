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

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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

    def test_find_supporting_articles_by_url_slug(self):
        from build.generate_weekly import _find_supporting_articles

        articles = [
            {
                "title": "Editor Review",
                "url": "https://elle.com/guerlain-rouge-lipstick-editor-review",
                "date": "2026-07-20",
            },
            {
                "title": "Hair Trends for Summer",
                "url": "https://elle.com/hair",
                "date": "2026-07-19",
            },
        ]
        result = _find_supporting_articles(
            "Guerlain Rouge Lipstick", "https://sephora.com/test", articles
        )
        assert len(result) == 1
        assert result[0]["url"] == "https://elle.com/guerlain-rouge-lipstick-editor-review"

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
# 12. generate_products batch behavior
# ══════════════════════════════════════════════════════════════════════════════


class TestGenerateProductsBatch:
    """Batch processing: quarantine unsupported products, renumber, validate panels."""

    @staticmethod
    def _make_llm_product(
        name: str,
        rank: int = 1,
        score: int = 85,
        market: str = "US",
        tier: str = "LUXURY",
        category_badge: str = "Foundation",
        source_url: str = "https://elle.com/article-1",
        link: str = "https://sephora.com/product",
    ) -> dict:
        return {
            "name": name,
            "name_cn": name,
            "rank": rank,
            "score": score,
            "market": market,
            "tier": tier,
            "category_badge": category_badge,
            "brand_cn": "brand_cn",
            "brand_en": "brand_en",
            "buzz_cn": "buzz_cn",
            "buzz_en": "buzz_en",
            "features_cn": "features_cn",
            "features_en": "features_en",
            "price_cn": "$50",
            "price_en": "$50",
            "link": link,
            "source_url": source_url,
        }

    def _make_response(self, heat: dict, radar: dict | None = None) -> str:
        return json.dumps(
            {
                "heat_rankings": heat,
                "new_product_radar": radar
                or {k: [] for k in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")},
            }
        )

    def test_mixed_supported_unsupported_retains_supported(self):
        """Supported products retained; unsupported products quarantined."""
        from build.generate_weekly import generate_products

        articles = [
            {
                "title": "Rare Beauty Blush Launch",
                "url": "https://elle.com/rare-beauty-blush",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Rare Beauty Blush is the hottest new launch",
            },
            {
                "title": "Fenty Foundation Review",
                "url": "https://elle.com/fenty-foundation",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Fenty Foundation is getting rave reviews",
            },
            {
                "title": "Chanel Lipstick Trends",
                "url": "https://elle.com/chanel-lipstick",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Chanel Lipstick is trending this season",
            },
            {
                "title": "Dior Skincare Essentials",
                "url": "https://elle.com/dior-skincare",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Dior Skincare essential for summer",
            },
        ]

        raw_data = {"articles": articles}

        heat = {
            "US LUXURY": [
                self._make_llm_product(
                    "Rare Beauty Blush",
                    rank=1,
                    score=88,
                    source_url="https://elle.com/rare-beauty-blush",
                    link="https://sephora.com/rare-beauty-blush",
                ),
                self._make_llm_product(
                    "Ghost Unsupportable",
                    rank=2,
                    score=75,
                    source_url="https://elle.com/ghost",
                    link="https://sephora.com/ghost",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Fenty Foundation",
                    rank=1,
                    score=85,
                    market="US",
                    tier="MASSTIGE",
                    source_url="https://elle.com/fenty-foundation",
                    link="https://sephora.com/fenty-foundation",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Chanel Lipstick",
                    rank=1,
                    score=82,
                    market="CN",
                    tier="LUXURY",
                    source_url="https://elle.com/chanel-lipstick",
                    link="https://tmall.com/chanel-lipstick",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Dior Skincare",
                    rank=1,
                    score=80,
                    market="CN",
                    tier="MASSTIGE",
                    source_url="https://elle.com/dior-skincare",
                    link="https://tmall.com/dior-skincare",
                ),
            ],
        }

        with patch("build.generate_weekly.call_llm", return_value=self._make_response(heat)):
            result = generate_products(
                raw_data, "makeup", "2026-W30", "test", "2026-07-22T00:00:00Z"
            )

        # Only Rare Beauty Blush retained in US LUXURY (ghost was quarantined)
        us_lux = result["heat_rankings"]["US LUXURY"]
        assert len(us_lux) == 1
        assert us_lux[0]["name"] == "Rare Beauty Blush"
        assert us_lux[0]["rank"] == 1

        # Other panels unchanged
        assert result["heat_rankings"]["US MASSTIGE"][0]["name"] == "Fenty Foundation"
        assert result["heat_rankings"]["CN LUXURY"][0]["name"] == "Chanel Lipstick"
        assert result["heat_rankings"]["CN MASSTIGE"][0]["name"] == "Dior Skincare"

    def test_all_unsupported_heat_panel_raises(self):
        """All products unsupported => empty heat panel => ValueError."""
        from build.generate_weekly import generate_products

        articles = [
            {
                "title": "Random Content",
                "url": "https://elle.com/article-1",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "No product mentions here at all",
            },
            {
                "title": "More Random",
                "url": "https://elle.com/article-2",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Still no product mentions",
            },
            {
                "title": "Other News",
                "url": "https://elle.com/article-3",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Beauty industry trends analysis",
            },
            {
                "title": "Final Article",
                "url": "https://elle.com/article-4",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Market research data",
            },
        ]

        raw_data = {"articles": articles}

        heat = {
            "US LUXURY": [
                self._make_llm_product(
                    "Random A",
                    source_url="https://elle.com/article-1",
                    link="https://sephora.com/a",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Random B",
                    source_url="https://elle.com/article-2",
                    market="US",
                    tier="MASSTIGE",
                    link="https://sephora.com/b",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Random C",
                    source_url="https://elle.com/article-3",
                    market="CN",
                    link="https://tmall.com/c",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Random D",
                    source_url="https://elle.com/article-4",
                    market="CN",
                    tier="MASSTIGE",
                    link="https://tmall.com/d",
                ),
            ],
        }

        with (
            patch("build.generate_weekly.call_llm", return_value=self._make_response(heat)),
            pytest.raises(ValueError, match="are empty after 3 attempts"),
        ):
            generate_products(raw_data, "makeup", "2026-W30", "test", "2026-07-22T00:00:00Z")

    def test_radar_unsupported_becomes_empty(self):
        """Unsupported radar products are dropped; heat panels must remain intact."""
        from build.generate_weekly import generate_products

        articles = [
            {
                "title": "Rare Beauty Blush Launch",
                "url": "https://elle.com/rare-beauty-blush",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Rare Beauty Blush is the hottest new launch",
            },
            {
                "title": "Fenty Foundation Review",
                "url": "https://elle.com/fenty-foundation",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Fenty Foundation is getting rave reviews",
            },
            {
                "title": "Chanel Lipstick Trends",
                "url": "https://elle.com/chanel-lipstick",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Chanel Lipstick is trending this season",
            },
            {
                "title": "Dior Skincare Essentials",
                "url": "https://elle.com/dior-skincare",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Dior Skincare essential for summer",
            },
            {
                "title": "Random Unrelated",
                "url": "https://elle.com/random",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Unrelated content",
            },
        ]

        raw_data = {"articles": articles}

        heat = {
            "US LUXURY": [
                self._make_llm_product(
                    "Rare Beauty Blush",
                    source_url="https://elle.com/rare-beauty-blush",
                    link="https://sephora.com/rare-beauty-blush",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Fenty Foundation",
                    source_url="https://elle.com/fenty-foundation",
                    market="US",
                    tier="MASSTIGE",
                    link="https://sephora.com/fenty-foundation",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Chanel Lipstick",
                    source_url="https://elle.com/chanel-lipstick",
                    market="CN",
                    link="https://tmall.com/chanel-lipstick",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Dior Skincare",
                    source_url="https://elle.com/dior-skincare",
                    market="CN",
                    tier="MASSTIGE",
                    link="https://tmall.com/dior-skincare",
                ),
            ],
        }

        radar = {
            "US LUXURY": [
                self._make_llm_product(
                    "Radar Ghost",
                    source_url="https://elle.com/random",
                    link="https://sephora.com/radar-ghost",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Radar Ghost 2",
                    source_url="https://elle.com/random",
                    market="US",
                    tier="MASSTIGE",
                    link="https://sephora.com/radar-ghost2",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Radar Ghost 3",
                    source_url="https://elle.com/random",
                    market="CN",
                    link="https://tmall.com/radar-ghost3",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Radar Ghost 4",
                    source_url="https://elle.com/random",
                    market="CN",
                    tier="MASSTIGE",
                    link="https://tmall.com/radar-ghost4",
                ),
            ],
        }

        with patch("build.generate_weekly.call_llm", return_value=self._make_response(heat, radar)):
            result = generate_products(
                raw_data, "makeup", "2026-W30", "test", "2026-07-22T00:00:00Z"
            )

        # Heat panels intact
        assert len(result["heat_rankings"]["US LUXURY"]) == 1
        assert result["heat_rankings"]["US LUXURY"][0]["name"] == "Rare Beauty Blush"

        # Radar panels should be empty — all radar products were unsupported
        for panel_key in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
            assert result["new_product_radar"][panel_key] == [], (
                f"Radar panel '{panel_key}' should be empty"
            )

    def test_non_collected_source_url_rejected(self):
        """Product with source_url not in collected articles must be quarantined."""
        from build.generate_weekly import generate_products

        articles = [
            {
                "title": "Beauty Roundup July 2026",
                "url": "https://elle.com/beauty-roundup",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Rare Beauty Blush is the hottest new launch. "
                "Fenty Foundation is getting rave reviews. "
                "Chanel Lipstick is trending this season. "
                "Dior Skincare essential for summer.",
            },
        ]

        raw_data = {"articles": articles}

        heat = {
            "US LUXURY": [
                self._make_llm_product(
                    "Rare Beauty Blush",
                    source_url="https://elle.com/beauty-roundup",
                    link="https://sephora.com/rare-beauty-blush",
                ),
                self._make_llm_product(
                    "Fake Source Product",
                    rank=2,
                    score=70,
                    source_url="https://fabricated.example.com/not-collected",
                    link="https://sephora.com/fake",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Fenty Foundation",
                    source_url="https://elle.com/beauty-roundup",
                    market="US",
                    tier="MASSTIGE",
                    link="https://sephora.com/fenty-foundation",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Chanel Lipstick",
                    source_url="https://elle.com/beauty-roundup",
                    market="CN",
                    link="https://tmall.com/chanel-lipstick",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Dior Skincare",
                    source_url="https://elle.com/beauty-roundup",
                    market="CN",
                    tier="MASSTIGE",
                    link="https://tmall.com/dior-skincare",
                ),
            ],
        }

        with patch("build.generate_weekly.call_llm", return_value=self._make_response(heat)):
            result = generate_products(
                raw_data, "makeup", "2026-W30", "test", "2026-07-22T00:00:00Z"
            )

        # The product with non-collected source_url must be absent
        names = [p["name"] for p in result["heat_rankings"]["US LUXURY"]]
        assert "Rare Beauty Blush" in names
        assert "Fake Source Product" not in names

        # Renumbering: only Rare Beauty Blush left, should be rank 1
        assert result["heat_rankings"]["US LUXURY"][0]["rank"] == 1

    def test_renumbering_after_filtering(self):
        """Ranks must be sequential starting from 1 after quarantine filtering."""
        from build.generate_weekly import generate_products

        articles = [
            {
                "title": "Product Alpha Review",
                "url": "https://elle.com/alpha",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Product Alpha is amazing",
            },
            {
                "title": "Product Beta Launch",
                "url": "https://elle.com/beta",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Product Beta is new",
            },
            {
                "title": "Product Gamma News",
                "url": "https://elle.com/gamma",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Product Gamma is trending",
            },
            {
                "title": "Product Delta Report",
                "url": "https://elle.com/delta",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Product Delta analysis",
            },
            {
                "title": "Random Unrelated",
                "url": "https://elle.com/random",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "No product mention",
            },
            {
                "title": "Chanel Lipstick China Launch",
                "url": "https://elle.com/chanel-china",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Chanel Lipstick is launching in China",
            },
            {
                "title": "Dior Skincare China Report",
                "url": "https://elle.com/dior-china",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Dior Skincare is growing in China",
            },
        ]

        raw_data = {"articles": articles}

        heat = {
            "US LUXURY": [
                self._make_llm_product(
                    "Product Alpha",
                    rank=1,
                    score=95,
                    source_url="https://elle.com/alpha",
                    link="https://sephora.com/alpha",
                ),
                self._make_llm_product(
                    "Ghost Mid",
                    rank=2,
                    score=85,
                    source_url="https://elle.com/random",
                    link="https://sephora.com/ghost-mid",
                ),
                self._make_llm_product(
                    "Product Beta",
                    rank=3,
                    score=80,
                    source_url="https://elle.com/beta",
                    link="https://sephora.com/beta",
                ),
                self._make_llm_product(
                    "Ghost End",
                    rank=4,
                    score=70,
                    source_url="https://elle.com/random",
                    link="https://sephora.com/ghost-end",
                ),
                self._make_llm_product(
                    "Product Gamma",
                    rank=5,
                    score=65,
                    source_url="https://elle.com/gamma",
                    link="https://sephora.com/gamma",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Product Delta",
                    rank=1,
                    score=80,
                    market="US",
                    tier="MASSTIGE",
                    source_url="https://elle.com/delta",
                    link="https://sephora.com/delta",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Chanel Lipstick",
                    source_url="https://elle.com/chanel-china",
                    market="CN",
                    link="https://tmall.com/chanel-lipstick",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Dior Skincare",
                    source_url="https://elle.com/dior-china",
                    market="CN",
                    tier="MASSTIGE",
                    link="https://tmall.com/dior-skincare",
                ),
            ],
        }

        with patch("build.generate_weekly.call_llm", return_value=self._make_response(heat)):
            result = generate_products(
                raw_data, "makeup", "2026-W30", "test", "2026-07-22T00:00:00Z"
            )

        us_lux = result["heat_rankings"]["US LUXURY"]
        # Ghost Mid and Ghost End were quarantined (source_url not in article_urls)
        # Retained: Product Alpha (rank 1), Product Beta (rank 2), Product Gamma (rank 3)
        assert len(us_lux) == 3
        assert us_lux[0]["name"] == "Product Alpha"
        assert us_lux[0]["rank"] == 1
        assert us_lux[1]["name"] == "Product Beta"
        assert us_lux[1]["rank"] == 2
        assert us_lux[2]["name"] == "Product Gamma"
        assert us_lux[2]["rank"] == 3

    def test_invalid_source_url_survives_by_name_match(self):
        """Invalid source_url (product page) is discarded; product survives
        only when its name matches a collected article for evidence."""
        from build.generate_weekly import generate_products

        articles = [
            {
                "title": "Rare Beauty Blush Summer Review",
                "url": "https://elle.com/rare-beauty-review",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Rare Beauty Blush is the must-have blush this summer",
            },
            {
                "title": "Fenty Foundation Review",
                "url": "https://elle.com/fenty-foundation",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Fenty Foundation is getting rave reviews",
            },
            {
                "title": "Chanel Lipstick Trends",
                "url": "https://elle.com/chanel-lipstick",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Chanel Lipstick is trending this season",
            },
            {
                "title": "Dior Skincare Essentials",
                "url": "https://elle.com/dior-skincare",
                "date": "Mon, 20 Jul 2026 18:00:00 +0000",
                "summary": "Dior Skincare essential for summer",
            },
        ]

        raw_data = {"articles": articles}

        heat = {
            "US LUXURY": [
                self._make_llm_product(
                    "Rare Beauty Blush",
                    rank=1,
                    score=88,
                    source_url="https://sephora.com/product/rare-beauty-blush",
                    link="https://sephora.com/rare-beauty-blush",
                ),
            ],
            "US MASSTIGE": [
                self._make_llm_product(
                    "Fenty Foundation",
                    source_url="https://elle.com/fenty-foundation",
                    market="US",
                    tier="MASSTIGE",
                    link="https://sephora.com/fenty-foundation",
                ),
            ],
            "CN LUXURY": [
                self._make_llm_product(
                    "Chanel Lipstick",
                    source_url="https://elle.com/chanel-lipstick",
                    market="CN",
                    link="https://tmall.com/chanel-lipstick",
                ),
            ],
            "CN MASSTIGE": [
                self._make_llm_product(
                    "Dior Skincare",
                    source_url="https://elle.com/dior-skincare",
                    market="CN",
                    tier="MASSTIGE",
                    link="https://tmall.com/dior-skincare",
                ),
            ],
        }

        with patch("build.generate_weekly.call_llm", return_value=self._make_response(heat)):
            result = generate_products(
                raw_data, "makeup", "2026-W30", "test", "2026-07-22T00:00:00Z"
            )

        us_lux = result["heat_rankings"]["US LUXURY"]
        assert len(us_lux) == 1
        assert us_lux[0]["name"] == "Rare Beauty Blush"

        ev = us_lux[0]["launch_evidence"]
        assert ev is not None
        assert ev["quarantine_status"] == "verified"
        assert ev["evidence"] is not None
        assert ev["evidence"]["url"] == "https://elle.com/rare-beauty-review"


# ══════════════════════════════════════════════════════════════════════════════
# 13. Category-aware article relevance selection
# ══════════════════════════════════════════════════════════════════════════════


class TestCategoryAwareArticleSelection:
    """Verify _select_category_relevant_articles surfaces category-relevant
    CN/US articles that would be missed by a naive first-15 slice, while
    maintaining the 30-record bound and deterministic ordering."""

    @staticmethod
    def _make_article(title: str, url: str, market: str, summary: str = "") -> dict:
        return {"title": title, "url": url, "market": market, "summary": summary}

    def test_relevant_cn_luxury_makeup_article_past_first_15(self):
        """A CN makeup article at index 20 should enter the prompt when the
        first 15 CN articles are all fragrance-related."""
        from build.generate_weekly import _select_category_relevant_articles

        # 16 CN articles: first 15 are fragrance, last one is makeup
        frag_cn = [
            self._make_article(
                f"Fragrance CN {i}",
                f"https://cn.example.com/frag-{i}",
                "CN",
                f"perfume release {i}",
            )
            for i in range(15)
        ]
        makeup_cn = [
            self._make_article(
                "Lipstick Launch CN",
                "https://cn.example.com/lipstick",
                "CN",
                "New luxury lipstick collection",
            )
        ]
        articles = (
            frag_cn
            + makeup_cn
            + [
                self._make_article(
                    "US Makeup Roundup",
                    "https://us.example.com/makeup",
                    "US",
                    "Foundation and blush review",
                ),
            ]
        )

        selected = _select_category_relevant_articles(articles, "makeup")
        selected_urls = [a["url"] for a in selected]

        # The makeup-relevant CN article should be selected
        assert "https://cn.example.com/lipstick" in selected_urls
        # Fragrance-only CN articles should be deprioritized / dropped
        assert "https://cn.example.com/frag-14" not in selected_urls

    def test_relevant_us_article_past_first_15(self):
        """A US fragrance article at index 20 should enter the prompt when
        the first 15 US articles are all makeup-related."""
        from build.generate_weekly import _select_category_relevant_articles

        makeup_us = [
            self._make_article(
                f"Makeup US {i}",
                f"https://us.example.com/makeup-{i}",
                "US",
                f"lipstick review {i}",
            )
            for i in range(15)
        ]
        fragrance_us = [
            self._make_article(
                "Perfume Launch US",
                "https://us.example.com/perfume",
                "US",
                "New eau de parfum fragrance release",
            )
        ]
        articles = (
            [
                self._make_article(
                    "CN Makeup Article",
                    "https://cn.example.com/mk",
                    "CN",
                    "blush collection",
                ),
            ]
            + makeup_us
            + fragrance_us
        )

        selected = _select_category_relevant_articles(articles, "fragrance")
        selected_urls = [a["url"] for a in selected]

        assert "https://us.example.com/perfume" in selected_urls
        assert "https://us.example.com/makeup-14" not in selected_urls

    def test_30_record_bound_respected(self):
        """At most 15 CN + 15 non-CN = 30 articles returned."""
        from build.generate_weekly import _select_category_relevant_articles

        articles = [
            self._make_article(
                f"Article {i}",
                f"https://example.com/{i}",
                "CN" if i < 30 else "US",
                f"fragrance perfume {i}",
            )
            for i in range(60)
        ]

        selected = _select_category_relevant_articles(articles, "fragrance")
        cn_count = sum(1 for a in selected if a.get("market") == "CN")
        non_cn_count = sum(1 for a in selected if a.get("market") != "CN")

        assert cn_count <= 15
        assert non_cn_count <= 15
        assert len(selected) <= 30

    def test_stable_ordering_for_equal_scores(self):
        """Articles with identical relevance scores keep their original order."""
        from build.generate_weekly import _select_category_relevant_articles

        articles = [
            self._make_article(
                f"Generic News {i}",
                f"https://news.example.com/{i}",
                "CN",
                "Industry analysis",
            )
            for i in range(20)
        ]

        selected = _select_category_relevant_articles(articles, "makeup")
        selected_urls = [a["url"] for a in selected]

        # All have score 0 — first 15 in insertion order should be kept
        assert len(selected) == 15
        for i in range(15):
            assert selected_urls[i] == f"https://news.example.com/{i}"

    def test_empty_articles_returns_empty(self):
        from build.generate_weekly import _select_category_relevant_articles

        assert _select_category_relevant_articles([], "makeup") == []

    def test_fewer_than_max_articles_returns_all(self):
        from build.generate_weekly import _select_category_relevant_articles

        articles = [
            self._make_article("Frag A", "https://a.com", "CN", "perfume"),
            self._make_article("Frag B", "https://b.com", "US", "cologne"),
        ]
        selected = _select_category_relevant_articles(articles, "fragrance")
        assert len(selected) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 14. build/validate_published.py CLI script
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
