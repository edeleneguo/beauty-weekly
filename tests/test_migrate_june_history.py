#!/usr/bin/env python3
"""Focused tests for the June historical recovery parser."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "build" / "migrate_june_history.py"


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("migrate_june_history", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_section_finds_heat_and_radar(migration_module):
    html = """
    <h2 class="section-title">
      Makeup <em>Heat</em> Rankings <span class="sec-label">Section 03</span>
    </h2>
    <div class="heat-section"><h4><span>US</span><span>LUXURY</span></h4><ul></ul></div>
    <h2 class="section-title">
      Makeup <em>New Product</em> Radar <span class="sec-label">Section 04</span>
    </h2>
    <div class="radar-section"><h4><span>US</span><span>MASSTIGE</span></h4><ul></ul></div>
    <!-- APPENDIX -->
    """

    heat = migration_module._extract_section(html, "heat_rankings")
    radar = migration_module._extract_section(html, "new_product_radar")

    assert "LUXURY" in heat
    assert "MASSTIGE" in radar


def test_extract_detail_cells_maps_render_labels(migration_module):
    item_html = """
    <div class="heat-detail-grid">
      <div class="heat-detail-cell">
        <div class="heat-detail-label">Price/Link</div>
        <div class="heat-detail-value">$45 <a href="https://example.com/p/1">🔗</a></div>
      </div>
      <div class="heat-detail-cell">
        <div class="heat-detail-label">
          Key Features <span class="heat-trend-tag">New Launches</span>
        </div>
        <div class="heat-detail-value">Ceramide gloss · high-shine finish</div>
      </div>
      <div class="heat-detail-cell">
        <div class="heat-detail-label">Buzz/Reviews/Sales</div>
        <div class="heat-detail-value">Editor preview positive</div>
      </div>
      <div class="heat-detail-cell">
        <div class="heat-detail-label">Launch/Category</div>
        <div class="heat-detail-value">2026.6.1 launch · 18 shades</div>
      </div>
    </div>
    """

    detail = migration_module._extract_detail_cells(item_html)

    assert detail["price_link"]["value"] == "$45"
    assert detail["price_link"]["link"] == "https://example.com/p/1"
    assert detail["key_features"]["trend_tag"] == "New Launches"
    assert detail["brand"]["value"] == "2026.6.1 launch · 18 shades"


def test_parse_item_collects_core_fields(migration_module):
    item_html = """
    <li class="heat-item">
      <div class="heat-item-header">
        <span class="heat-rank us">5</span>
        <div class="heat-info">
          <span class="heat-name">Rouge Coco Hydra Gloss</span>
          <span class="heat-cat-badge">High-Shine Lipgloss</span>
          <span class="heat-trend-badge">Trend</span>
          <span class="heat-new-badge">NEW</span>
        </div>
        <div class="heat-score-stack"><span class="heat-score">75</span></div>
      </div>
      <div class="heat-detail">
        <div class="heat-detail-grid">
          <div class="heat-detail-cell">
            <div class="heat-detail-label">Price/Link</div>
            <div class="heat-detail-value">$45 <a href="https://www.chanel.com/p/1">🔗</a></div>
          </div>
          <div class="heat-detail-cell">
            <div class="heat-detail-label">
              Key Features <span class="heat-trend-tag">Efficacy Lip Trend</span>
            </div>
            <div class="heat-detail-value">85% moisture base</div>
          </div>
          <div class="heat-detail-cell">
            <div class="heat-detail-label">Buzz/Reviews/Sales</div>
            <div class="heat-detail-value">Editorial preview positive</div>
          </div>
          <div class="heat-detail-cell">
            <div class="heat-detail-label">Launch/Category</div>
            <div class="heat-detail-value">2026.6.1 Summer collection</div>
          </div>
        </div>
      </div>
    </li>
    """

    item = migration_module._parse_item(
        item_html,
        topic="makeup",
        section="new_product_radar",
        panel="US LUXURY",
        week="week-26",
        path="archive/week-26/index.html",
    )

    assert item["product_name"] == "Rouge Coco Hydra Gloss"
    assert item["trend_badge"] == "Trend"
    assert item["new_badge"] == "NEW"
    assert item["explicit_dates"] == ["2026-06-01"]
    assert item["detail"]["price_link"] == "https://www.chanel.com/p/1"
    assert item["trend_tag"] == "Efficacy Lip Trend"


def test_week27_filter_requires_item_level_june_29_or_30(migration_module):
    candidate = {
        "explicit_dates": ["2026-06-30"],
    }
    excluded = {
        "explicit_dates": ["2026-06-01"],
    }

    assert migration_module._should_include_candidate("week-27", candidate) is True
    assert migration_module._should_include_candidate("week-27", excluded) is False
    assert migration_module._should_include_candidate("week-26", excluded) is True


def test_dedupe_preserves_all_provenance(migration_module):
    first = {
        "topic": "makeup",
        "section": "heat_rankings",
        "panel": "US LUXURY",
        "product_name": "Product A",
        "score": 80,
        "rank": 2,
        "detail": {"price_link": "", "key_features": "", "buzz": "", "brand": ""},
        "explicit_dates": [],
        "source_snapshot": {
            "commit": "709c63b",
            "commit_url": "https://example.com",
            "week": "week-23",
            "path": "archive/week-23/index.html",
        },
    }
    second = {
        "topic": "makeup",
        "section": "heat_rankings",
        "panel": "US LUXURY",
        "product_name": "Product A",
        "score": 83,
        "rank": 1,
        "detail": {"price_link": "$40", "key_features": "x", "buzz": "y", "brand": "z"},
        "explicit_dates": ["2026-06-15"],
        "source_snapshot": {
            "commit": "709c63b",
            "commit_url": "https://example.com",
            "week": "week-26",
            "path": "archive/week-26/index.html",
        },
    }

    deduped, duplicates = migration_module._dedupe_candidates([first, second])

    assert duplicates == 1
    assert len(deduped) == 1
    assert deduped[0]["score"] == 83
    assert len(deduped[0]["provenance"]) == 2
