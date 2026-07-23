"""Renderer unit tests for radar product trend_badge/trend_rationale rendering.

Requirement: Every qualifying radar product must fail validation unless
trend_badge, trend_id, trend_tag, and trend_rationale are all nonempty.
Production may have zero qualifying radar items.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from build.render import _render_product  # noqa: E402


def _make_radar_product(
    trend_badge="Trend",
    trend_tag="Skincare Foundation",
    trend_rationale="Test rationale for skincare foundation trend",
    trend_id="trend_skincare_foundation",
    score=85,
):
    """Build a minimal radar product dict with all trend metadata."""
    return {
        "rank": 1,
        "market": "US",
        "tier": "LUXURY",
        "name": "Test Product Radar",
        "category_badge": "Test Category",
        "score": score,
        "trend_badge": trend_badge,
        "trend_tag": trend_tag,
        "trend_rationale": trend_rationale,
        "trend_id": trend_id,
        "detail": {
            "price_link": {"en": "$50", "cn": "$50", "link": "https://example.com"},
            "key_features": {"en": "Feature 1", "cn": "Feature 1"},
            "buzz": {"en": "Buzz 1", "cn": "Buzz 1"},
            "brand": {"en": "Brand 1", "cn": "Brand 1"},
        },
    }


class TestRadarTrendRendering:
    """Verify that radar products render trend badge and <details> rationale."""

    def test_radar_with_trend_renders_badge_and_details(self):
        """A radar product with trend_badge must render both the badge span and
        an expandable <details> element containing the trend rationale."""
        product = _make_radar_product()
        html = _render_product(product, "en", "radar")

        # Must contain the trend badge span
        assert "heat-trend-badge" in html, "Missing trend badge in radar HTML"
        assert "Trend" in html, "Trend badge text not rendered"

        # Must contain the trend tag
        assert "heat-trend-tag" in html, "Missing trend tag in radar HTML"
        assert "Skincare Foundation" in html, "Trend tag text not rendered"

        # Must contain expandable <details> with rationale
        assert "<details" in html, "Missing <details> element for trend rationale"
        assert "Rationale" in html, "Missing Rationale summary text"
        assert "Test rationale for skincare foundation trend" in html, (
            "Trend rationale text not rendered inside <details>"
        )

    def test_radar_without_trend_no_badge(self):
        """A radar product without trend_badge must not render trend badge or details."""
        product = _make_radar_product(trend_badge=None, trend_tag=None, trend_rationale=None)
        html = _render_product(product, "en", "radar")

        assert "heat-trend-badge" not in html, "Spurious trend badge rendered"
        assert "<details" not in html, "Spurious <details> element rendered"

    def test_radar_trend_html_structure(self):
        """Verify the exact HTML structure of the rendered trend section."""
        product = _make_radar_product(
            trend_tag="Milky Musk",
            trend_rationale="Gourmand milk musk resurgence across CN and US markets",
        )
        html = _render_product(product, "en", "radar")

        # Check the trend detail div structure
        assert '<div class="heat-detail"' in html
        assert '<span class="heat-trend-tag"' in html
        assert "Milky Musk" in html
        assert "<details" in html
        assert "<summary" in html
        assert "Gourmand milk musk resurgence" in html

    def test_radar_renders_launch_evidence_grade(self):
        product = _make_radar_product()
        product["launch_evidence"] = {
            "launch_date": "2026-06-12",
            "quarantine_status": "verified",
            "evidence_grade": "A",
            "date_basis": "official_launch",
        }
        html = _render_product(product, "en", "radar")
        assert "Launch Evidence" in html
        assert "Grade A" in html
        assert "2026-06-12" in html
        assert "official launch" in html


class TestRadarTrendValidation:
    """Verify that validation catches missing trend metadata on radar products."""

    def test_radar_with_trend_badge_but_missing_rationale_fails(self):
        """A radar product with trend_badge but no trend_rationale must produce
        a missing-trend-rationale validation error."""
        from build.validate import _check_data_consistency

        # Build a data dict with a radar product that has trend_badge but no rationale
        data = {
            "date_range": {"start": "2026-06-01", "end": "2026-06-30"},
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                    "new_product_radar": {
                        "US LUXURY": [
                            {
                                "rank": 1,
                                "market": "US",
                                "tier": "LUXURY",
                                "name": "Incomplete Trend Product",
                                "category_badge": "Test",
                                "score": 85,
                                "detail": {
                                    "price_link": {"en": "$50", "cn": "$50", "link": ""},
                                    "key_features": {"en": "F", "cn": "F"},
                                    "buzz": {"en": "B", "cn": "B"},
                                    "brand": {"en": "Br", "cn": "Br"},
                                },
                                "trend_badge": "Trend",
                                "trend_id": "trend_test",
                                "trend_tag": "Skincare Foundation",
                                "trend_rationale": None,  # Missing!
                            }
                        ],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                },
                "fragrance": {
                    "heat_rankings": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                    "new_product_radar": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                },
            },
        }

        issues = _check_data_consistency(data)
        rationale_issues = [i for i in issues if i.rule == "missing-trend-rationale"]
        assert len(rationale_issues) == 1, (
            f"Expected 1 missing-trend-rationale issue, got {len(rationale_issues)}"
        )
        assert "Incomplete Trend Product" in rationale_issues[0].file

    def test_radar_with_all_trend_fields_passes(self):
        """A radar product with all trend fields populated must not produce
        trend-related validation errors."""
        from build.validate import _check_data_consistency

        data = {
            "date_range": {"start": "2026-06-01", "end": "2026-06-30"},
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                    "new_product_radar": {
                        "US LUXURY": [
                            {
                                "rank": 1,
                                "market": "US",
                                "tier": "LUXURY",
                                "name": "Complete Trend Product",
                                "category_badge": "Test",
                                "score": 85,
                                "detail": {
                                    "price_link": {"en": "$50", "cn": "$50", "link": ""},
                                    "key_features": {"en": "F", "cn": "F"},
                                    "buzz": {"en": "B", "cn": "B"},
                                    "brand": {"en": "Br", "cn": "Br"},
                                },
                                "trend_badge": "Trend",
                                "trend_id": "trend_skincare_foundation",
                                "trend_tag": "Skincare Foundation",
                                "trend_rationale": "Full rationale present",
                            }
                        ],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                },
                "fragrance": {
                    "heat_rankings": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                    "new_product_radar": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                },
            },
        }

        issues = _check_data_consistency(data)
        trend_issues = [
            i
            for i in issues
            if i.rule in ("missing-trend-id", "missing-trend-tag-field", "missing-trend-rationale")
        ]
        assert len(trend_issues) == 0, (
            f"Expected 0 trend issues, got {len(trend_issues)}: {trend_issues}"
        )

    def test_radar_with_trend_badge_and_nested_trend_object_passes(self):
        """A radar product with trend_badge and a nested trend object (canonical format)
        must pass validation when the trend object has all required fields."""
        from build.validate import _check_data_consistency

        data = {
            "date_range": {"start": "2026-06-01", "end": "2026-06-30"},
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                    "new_product_radar": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                },
                "fragrance": {
                    "heat_rankings": {
                        "US LUXURY": [],
                        "US MASSTIGE": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                    "new_product_radar": {
                        "US MASSTIGE": [
                            {
                                "rank": 1,
                                "market": "US",
                                "tier": "MASSTIGE",
                                "name": "Nested Trend Product",
                                "category_badge": "Test",
                                "score": 85,
                                "detail": {
                                    "price_link": {"en": "$50", "cn": "$50", "link": ""},
                                    "key_features": {"en": "F", "cn": "F"},
                                    "buzz": {"en": "B", "cn": "B"},
                                    "brand": {"en": "Br", "cn": "Br"},
                                },
                                "trend_badge": "Trend",
                                # Flat fields are None — trend data is in nested object
                                "trend_id": None,
                                "trend_tag": None,
                                "trend_rationale": None,
                                "trend": {
                                    "id": "trend_milky_musk",
                                    "tag": "Milky Musk",
                                    "tag_cn": "乳感麝香趋势",
                                    "rationale": "Gourmand milk musk resurgence",
                                },
                            }
                        ],
                        "US LUXURY": [],
                        "CN LUXURY": [],
                        "CN MASSTIGE": [],
                    },
                },
            },
        }

        issues = _check_data_consistency(data)
        trend_issues = [
            i
            for i in issues
            if i.rule in ("missing-trend-id", "missing-trend-tag-field", "missing-trend-rationale")
            and "Nested Trend Product" in i.message
        ]
        assert len(trend_issues) == 0, (
            f"Expected 0 trend issues for nested trend object, got {len(trend_issues)}: "
            f"{trend_issues}"
        )
