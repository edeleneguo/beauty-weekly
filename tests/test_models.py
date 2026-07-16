#!/usr/bin/env python3
"""Tests for beauty_weekly models, loader, and adapter.

Covers:
  1. Successful loading of legacy data/week28.json
  2. Invalid enum / score / trend reference failures (strict + extra forbid)
  3. Bilingual shared-identity invariants
  4. Legacy exact JSON roundtrip / no-loss behaviour
  5. Manifest canonical-directory integrity
  6. Migration gap documentation
"""

import json
from pathlib import Path

import pytest
from beauty_weekly.loader import (
    LEGACY_ISOLATED_FIELDS,
    MIGRATION_GAPS,
    load_legacy_raw,
    load_legacy_report,
    load_report,
    to_target,
    validate_legacy,
)
from beauty_weekly.models import (
    LaunchEvidence,
    LegacyLocalizedText,
    LegacyPriceLink,
    LegacyProduct,
    LegacyProductDetail,
    LegacyWeeklyReport,
    LocalizedText,
    Market,
    PriceLink,
    Product,
    ProductDetail,
    Products,
    Tier,
    WeeklyReport,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "week28.json"
MANIFEST_PATH = ROOT / "data" / "weeks" / "2026-W28" / "manifest.json"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _legacy_product(**overrides):
    """Build a minimal valid LegacyProduct."""
    defaults = dict(
        rank=1,
        market="US",
        tier="LUXURY",
        name="X",
        category_badge="Cat",
        score=80,
        detail=LegacyProductDetail(
            price_link=LegacyPriceLink(en="x", cn="x", link="http://x"),
            key_features=LegacyLocalizedText(en="x", cn="x"),
            buzz=LegacyLocalizedText(en="x", cn="x"),
            brand=LegacyLocalizedText(en="x", cn="x"),
        ),
    )
    defaults.update(overrides)
    return LegacyProduct(**defaults)


def _target_product(**overrides):
    """Build a minimal valid target Product."""
    defaults = dict(
        rank=1,
        market=Market.US,
        tier=Tier.LUXURY,
        name="X",
        category_badge="Cat",
        score=80,
        detail=ProductDetail(
            price_link=PriceLink(en="x", cn="x", link="http://x"),
            key_features=LocalizedText(en="x", cn="x"),
            buzz=LocalizedText(en="x", cn="x"),
            brand=LocalizedText(en="x", cn="x"),
        ),
    )
    defaults.update(overrides)
    return Product(**defaults)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def raw_data():
    return load_legacy_raw(DATA_PATH)


@pytest.fixture(scope="session")
def legacy_report():
    return load_legacy_report(DATA_PATH)


@pytest.fixture(scope="session")
def target_report():
    report, _warnings = load_report(DATA_PATH)
    return report


@pytest.fixture(scope="session")
def manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Successful loading
# ══════════════════════════════════════════════════════════════════════════════


class TestSuccessfulLoading:
    def test_legacy_loads(self, legacy_report):
        assert isinstance(legacy_report, LegacyWeeklyReport)
        assert legacy_report.week == 28

    def test_target_loads(self, target_report):
        assert isinstance(target_report, WeeklyReport)
        assert target_report.week == 28

    def test_all_topics_present(self, legacy_report, target_report):
        for model in (legacy_report, target_report):
            assert "US LUXURY" in model.products.makeup.heat_rankings
            assert "CN MASSTIGE" in model.products.fragrance.heat_rankings

    def test_heat_product_count(self, legacy_report):
        total = sum(len(ps) for ps in legacy_report.products.makeup.heat_rankings.values())
        assert total == 40

    def test_radar_product_count(self, legacy_report):
        total = sum(len(ps) for ps in legacy_report.products.fragrance.new_product_radar.values())
        assert total > 0

    def test_manifest_loads(self, manifest):
        assert manifest["week"] == 28
        assert manifest["iso_week"] == "2026-W28"

    def test_validate_legacy_returns_warnings(self):
        warnings = validate_legacy(DATA_PATH)
        assert isinstance(warnings, list)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Strict + extra forbid validation
# ══════════════════════════════════════════════════════════════════════════════


class TestStrictValidation:
    def test_invalid_market_rejected(self):
        with pytest.raises(ValidationError):
            _target_product(market="EU")

    def test_invalid_tier_rejected(self):
        with pytest.raises(ValidationError):
            _target_product(tier="PRESTIGE")

    def test_invalid_quarantine_status_rejected(self):
        with pytest.raises(ValidationError):
            LaunchEvidence(
                launch_date="2026-07-07",
                quarantine_status="pending_review",
            )

    def test_legacy_accepts_any_string_for_market(self):
        lp = _legacy_product(market="EU")
        assert lp.market == "EU"

    def test_invalid_panel_key_rejected(self):
        with pytest.raises(ValidationError, match="Invalid panel key"):
            raw = {
                "week": 28,
                "date_range": "Jul 7 – Jul 13, 2026",
                "date_range_cn": "7月7日 – 7月13日",
                "version": "v1",
                "products": {
                    "makeup": {
                        "heat_rankings": {"US PRESTIGE": []},
                        "new_product_radar": {},
                    },
                    "fragrance": {
                        "heat_rankings": {},
                        "new_product_radar": {},
                    },
                },
            }
            LegacyWeeklyReport.model_validate(raw)

    def test_invalid_week_range_rejected(self):
        with pytest.raises(ValidationError):
            WeeklyReport(
                week=0,
                date_range="x",
                date_range_cn="x",
                version="v",
                products=Products(),
            )

    def test_target_extra_forbid(self):
        """Target model rejects unknown fields."""
        with pytest.raises(ValidationError):
            Product(
                rank=1,
                market=Market.US,
                tier=Tier.LUXURY,
                name="X",
                category_badge="Cat",
                score=80,
                detail=ProductDetail(
                    price_link=PriceLink(en="x", cn="x", link="http://x"),
                    key_features=LocalizedText(en="x", cn="x"),
                    buzz=LocalizedText(en="x", cn="x"),
                    brand=LocalizedText(en="x", cn="x"),
                ),
                bogus_field="should fail",
            )

    def test_legacy_extra_forbid(self):
        """Legacy model rejects unknown fields."""
        with pytest.raises(ValidationError):
            _legacy_product(bogus_field="should fail")

    def test_negative_score_rejected(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            _target_product(score=-1)

    def test_legacy_preserves_raw_score(self, legacy_report):
        p = None
        for prod in legacy_report.products.fragrance.heat_rankings.get("CN LUXURY", []):
            if prod.raw_score is not None:
                p = prod
                break
        assert p is not None
        assert p.raw_score < p.score


# ══════════════════════════════════════════════════════════════════════════════
# 3. Bilingual shared-identity invariants
# ══════════════════════════════════════════════════════════════════════════════


class TestBilingualInvariants:
    def test_localized_text_requires_both(self):
        with pytest.raises(ValidationError):
            LocalizedText(en="hello", cn="")
        with pytest.raises(ValidationError):
            LocalizedText(en="", cn="你好")

    def test_price_link_allows_empty_link(self):
        """PriceLink allows empty link (legacy gap — some products lack URLs)."""
        pl = PriceLink(en="x", cn="x", link="")
        assert pl.link == ""

    def test_all_legacy_products_have_bilingual_details(self, legacy_report):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = getattr(getattr(legacy_report.products, topic), section)
                for _panel, products in panels.items():
                    for p in products:
                        if p.score == 0:
                            continue
                        for cell_name in ("price_link", "key_features", "buzz", "brand"):
                            cell = getattr(p.detail, cell_name)
                            assert cell.en, f"{p.name}: {cell_name}.en empty"
                            assert cell.cn, f"{p.name}: {cell_name}.cn empty"

    def test_date_range_bilingual(self, legacy_report):
        assert legacy_report.date_range
        assert legacy_report.date_range_cn


# ══════════════════════════════════════════════════════════════════════════════
# 4. Legacy exact JSON roundtrip
# ══════════════════════════════════════════════════════════════════════════════


class TestLegacyRoundTrip:
    def test_exact_roundtrip(self, raw_data, legacy_report):
        """model_validate → model_dump must produce identical JSON."""
        dumped = legacy_report.model_dump(mode="json", exclude_unset=True)
        assert dumped == raw_data

    def test_all_product_names_preserved(self, raw_data, legacy_report):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                raw_panels = raw_data["products"][topic][section]
                model_section = getattr(getattr(legacy_report.products, topic), section)
                for panel, raw_products in raw_panels.items():
                    raw_names = [p["name"] for p in raw_products]
                    model_names = [p.name for p in model_section[panel]]
                    assert raw_names == model_names

    def test_target_adapter_preserves_count(self, raw_data, target_report):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                raw_count = sum(len(ps) for ps in raw_data["products"][topic][section].values())
                target_section = getattr(getattr(target_report.products, topic), section)
                target_count = sum(len(ps) for ps in target_section.values())
                assert raw_count == target_count

    def test_target_trend_mapping(self, legacy_report, target_report):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                legacy_section = getattr(getattr(legacy_report.products, topic), section)
                target_section = getattr(getattr(target_report.products, topic), section)
                for panel in legacy_section:
                    for lp, tp in zip(legacy_section[panel], target_section[panel]):
                        if lp.trend_badge and lp.trend_id:
                            assert tp.trend is not None
                            assert tp.trend.id == lp.trend_id
                        elif lp.trend_badge and not lp.trend_id:
                            assert tp.trend is None
                        else:
                            assert tp.trend is None

    def test_target_launch_evidence_mapping(self, legacy_report, target_report):
        for section in ("heat_rankings", "new_product_radar"):
            lps = getattr(legacy_report.products.fragrance, section)
            tps = getattr(target_report.products.fragrance, section)
            for panel in lps:
                for lp, tp in zip(lps[panel], tps[panel]):
                    if lp.quarantine_status is not None:
                        assert tp.launch_evidence is not None
                    else:
                        assert tp.launch_evidence is None

    def test_makeup_radar_has_no_launch_evidence(self, target_report):
        for _panel, products in target_report.products.makeup.new_product_radar.items():
            for p in products:
                assert p.launch_evidence is None

    def test_version_fields_preserved(self, raw_data, legacy_report):
        assert legacy_report.version == raw_data["version"]
        assert legacy_report.version_en_makeup == raw_data.get("version_en_makeup")
        assert legacy_report.version_cn_makeup == raw_data.get("version_cn_makeup")


# ══════════════════════════════════════════════════════════════════════════════
# 5. Migration gap documentation
# ══════════════════════════════════════════════════════════════════════════════


class TestMigrationGaps:
    def test_isolated_fields_documented(self):
        expected = {
            "raw_score",
            "version_en_makeup",
            "version_cn_makeup",
            "version_en_fragrance",
            "version_cn_fragrance",
            "category_badge_cn",
        }
        assert expected == set(LEGACY_ISOLATED_FIELDS.keys())

    def test_migration_gaps_documented(self):
        assert len(MIGRATION_GAPS) >= 2
        assert "makeup.radar.launch_evidence" in MIGRATION_GAPS
        assert "trend_tags_in_key_features" in MIGRATION_GAPS

    def test_to_target_returns_warnings(self, legacy_report):
        target, warnings = to_target(legacy_report)
        assert isinstance(target, WeeklyReport)
        assert isinstance(warnings, list)
        # Empty links and trend metadata gaps should produce warnings
        assert len(warnings) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 6. Manifest canonical-directory integrity
# ══════════════════════════════════════════════════════════════════════════════


class TestManifestIntegrity:
    def test_manifest_exists(self):
        assert MANIFEST_PATH.exists()

    def test_manifest_pointer_is_relative(self, manifest):
        assert manifest["data_pointer"].startswith("../../")

    def test_manifest_no_full_dataset(self, manifest):
        assert "products" not in manifest

    def test_canonical_dir_exists(self):
        assert (ROOT / "data" / "weeks" / "2026-W28").is_dir()
