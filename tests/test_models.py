#!/usr/bin/env python3
"""Tests for beauty_weekly models, loader, and adapter.

Covers:
  1. Successful loading of legacy data/week28.json
  2. Invalid enum / score / trend reference failures (strict + extra forbid)
  3. Bilingual shared-identity invariants
  4. Legacy exact JSON roundtrip / no-loss behaviour
  5. Manifest canonical-directory integrity
  6. Migration gap documentation
  7. Phase 3 domain model separation and trend extraction
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
    EvidenceAbsence,
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
    QuarantineStatus,
    ScoreBreakdown,
    Tier,
    Trend,
    TrendTag,
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

    def test_launch_evidence_accepts_auditable_grade_and_date_basis(self):
        evidence = LaunchEvidence(
            launch_date="2026-06-12",
            quarantine_status="verified",
            evidence_grade="A",
            date_basis="official_launch",
        )
        assert evidence.evidence_grade == "A"
        assert evidence.date_basis == "official_launch"

    def test_launch_evidence_rejects_unknown_grade(self):
        with pytest.raises(ValidationError):
            LaunchEvidence(
                launch_date="2026-06-12",
                quarantine_status="verified",
                evidence_grade="D",
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

    def test_score_breakdown_matches_product_score(self):
        product = _target_product(
            score=80,
            score_breakdown={
                "methodology": "Weighted display explanation",
                "recomputable": False,
                "total": 80,
                "components": [
                    {
                        "id": "sales_momentum",
                        "label": "Sales Momentum",
                        "weight": 0.40,
                        "max_points": 40,
                        "points": 32,
                        "evidence": "Sales proxy",
                    },
                    {
                        "id": "buzz_momentum",
                        "label": "Buzz Momentum",
                        "weight": 0.30,
                        "max_points": 30,
                        "points": 24,
                        "evidence": "Buzz proxy",
                    },
                    {
                        "id": "review_rating",
                        "label": "Review / Rating",
                        "weight": 0.20,
                        "max_points": 20,
                        "points": 16,
                        "evidence": "Review proxy",
                    },
                    {
                        "id": "trend_fit",
                        "label": "Trend Fit",
                        "weight": 0.10,
                        "max_points": 10,
                        "points": 8,
                        "evidence": "Trend fit",
                    },
                ],
            },
            data_quality={
                "source_type": "editorial",
                "link_type": "editorial_evidence",
                "coverage_score": 83,
                "coverage": {
                    "price": True,
                    "link": True,
                    "features": True,
                    "buzz": True,
                    "positioning": True,
                    "launch_evidence": False,
                },
                "missing_fields": ["launch_evidence"],
                "note": "Editorial fallback",
            },
        )
        assert product.score_breakdown is not None
        assert product.score_breakdown.total == 80
        assert product.data_quality is not None
        assert product.data_quality.coverage_score == 83

    def test_score_breakdown_rejects_invalid_total(self):
        with pytest.raises(ValidationError, match="component points must sum"):
            ScoreBreakdown(
                methodology="Weighted display explanation",
                recomputable=False,
                total=80,
                components=[
                    {
                        "id": "sales_momentum",
                        "label": "Sales Momentum",
                        "weight": 0.40,
                        "max_points": 40,
                        "points": 40,
                        "evidence": "Sales proxy",
                    },
                    {
                        "id": "buzz_momentum",
                        "label": "Buzz Momentum",
                        "weight": 0.30,
                        "max_points": 30,
                        "points": 30,
                        "evidence": "Buzz proxy",
                    },
                    {
                        "id": "review_rating",
                        "label": "Review / Rating",
                        "weight": 0.20,
                        "max_points": 20,
                        "points": 20,
                        "evidence": "Review proxy",
                    },
                    {
                        "id": "trend_fit",
                        "label": "Trend Fit",
                        "weight": 0.10,
                        "max_points": 10,
                        "points": 10,
                        "evidence": "Trend fit",
                    },
                ],
            )

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
                            # Radar product with flat fields — full Trend
                            assert tp.trend is not None
                            assert tp.trend.id == lp.trend_id
                        elif lp.trend_badge and lp.detail.key_features.trend_tags:
                            # Heat product — Trend extracted from key_features
                            assert tp.trend is not None
                            tag = lp.detail.key_features.trend_tags[0]
                            assert tp.trend.tag == tag
                            assert tp.trend.rationale is None
                        elif lp.trend_badge and not lp.trend_id:
                            # No trend data available — trend is None
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


# ══════════════════════════════════════════════════════════════════════════════
# 7. Phase 3 domain model separation and trend extraction
# ══════════════════════════════════════════════════════════════════════════════


class TestPhase3DomainModel:
    """Phase 3: structured domain model with trend extraction and evidence absence."""

    def test_trend_tag_bilingual_pair(self):
        """TrendTag requires both en and cn, rejects extras."""
        tt = TrendTag(en="Skincare Foundation", cn="养肤底妆趋势")
        assert tt.en == "Skincare Foundation"
        assert tt.cn == "养肤底妆趋势"
        with pytest.raises(ValidationError):
            TrendTag(en="", cn="养肤底妆趋势")
        with pytest.raises(ValidationError):
            TrendTag(en="Skincare Foundation", cn="")
        with pytest.raises(ValidationError):
            TrendTag(en="Skincare Foundation", cn="养肤底妆趋势", bogus="x")

    def test_evidence_absence_model(self):
        """EvidenceAbsence records gap reason and type."""
        ea = EvidenceAbsence(reason="No URL provided", gap_type="no_url")
        assert ea.reason == "No URL provided"
        assert ea.gap_type == "no_url"
        with pytest.raises(ValidationError):
            EvidenceAbsence(reason="", gap_type="no_url")
        with pytest.raises(ValidationError):
            EvidenceAbsence(reason="x", gap_type="x", bogus=True)

    def test_trend_rationale_optional(self):
        """Trend.rationale is optional — heat products have None."""
        t = Trend(id="trend_skincare", tag="Skincare Foundation", tag_cn="养肤底妆趋势")
        assert t.rationale is None
        t2 = Trend(
            id="trend_milky_musk",
            tag="Milky Musk",
            tag_cn="乳感麝香趋势",
            rationale="Gourmand milk/musk resurgence",
        )
        assert t2.rationale == "Gourmand milk/musk resurgence"

    def test_launch_evidence_has_absence_markers(self):
        """LaunchEvidence supports explicit absence markers."""
        le = LaunchEvidence(
            launch_date="2026-H1",
            quarantine_status=QuarantineStatus.OUT_OF_WINDOW,
            quarantine_reason="Vague date",
            absence_markers=[
                EvidenceAbsence(reason="Vague date 2026-H1", gap_type="vague_date"),
            ],
        )
        assert len(le.absence_markers) == 1
        assert le.absence_markers[0].gap_type == "vague_date"

    def test_heat_trends_extracted_from_key_features(self, legacy_report, target_report):
        """All 18 heat trend-badge products now have Trend extracted from key_features."""
        count_extracted = 0
        for topic in ("makeup", "fragrance"):
            lps = getattr(legacy_report.products, topic).heat_rankings
            tps = getattr(target_report.products, topic).heat_rankings
            for panel in lps:
                for lp, tp in zip(lps[panel], tps[panel]):
                    if lp.trend_badge and lp.detail.key_features.trend_tags:
                        assert tp.trend is not None
                        assert tp.trend.tag == lp.detail.key_features.trend_tags[0]
                        assert tp.trend.tag_cn == lp.detail.key_features.trend_tags_cn[0]
                        assert tp.trend.rationale is None
                        count_extracted += 1
        assert count_extracted >= 10, (
            f"Expected at least 10 heat trends extracted, got {count_extracted}"
        )

    def test_radar_trends_still_use_flat_fields(self, legacy_report, target_report):
        """Radar products with flat trend fields still use them (with rationale)."""
        lps = legacy_report.products.fragrance.new_product_radar
        tps = target_report.products.fragrance.new_product_radar
        for panel in lps:
            for lp, tp in zip(lps[panel], tps[panel]):
                if lp.trend_badge and lp.trend_id:
                    assert tp.trend is not None
                    assert tp.trend.id == lp.trend_id
                    assert tp.trend.tag == lp.trend_tag
                    assert tp.trend.rationale is not None

    def test_migration_warnings_reduced_to_two(self):
        """Phase 3: only 2 warnings remain (empty links on CN niche fragrances)."""
        _, warnings = load_report(DATA_PATH)
        assert len(warnings) == 2
        assert all("empty link" in w for w in warnings)

    def test_absence_markers_populated_for_radar(self, target_report):
        """Radar products with missing evidence get absence_markers."""
        fps = target_report.products.fragrance.new_product_radar
        for _panel, products in fps.items():
            for p in products:
                if p.launch_evidence is not None:
                    assert isinstance(p.launch_evidence.absence_markers, list)

    def test_manifest_phase3_metadata(self, manifest):
        """Manifest has Phase 3 metadata: schema_version >= 2, resolved_warnings."""
        assert manifest["schema_version"] >= 2
        assert "resolved_warnings" in manifest
        assert "remaining_warnings" in manifest
        assert manifest["remaining_warnings"] == 2
        assert len(manifest["resolved_warnings"]) >= 1

    def test_domain_separation_documented(self, manifest):
        """Manifest documents the five domain separation concerns."""
        assert "domain_separation" in manifest
        ds = manifest["domain_separation"]
        assert len(ds) >= 5
        assert any("trend" in item.lower() for item in ds)
        assert any("evidence" in item.lower() for item in ds)
        assert any("scoring" in item.lower() for item in ds)

    def test_trend_id_deterministic_derivation(self):
        """Derived trend IDs are deterministic from canonical tag names."""
        from beauty_weekly.loader import _map_legacy_trend
        from beauty_weekly.models import LegacyLocalizedText, LegacyPriceLink, LegacyProductDetail

        lp = _legacy_product(
            trend_badge="Trend",
            detail=LegacyProductDetail(
                price_link=LegacyPriceLink(en="x", cn="x", link="http://x"),
                key_features=LegacyLocalizedText(
                    en="test",
                    cn="test",
                    trend_tags=["Low-Saturation Pastel"],
                    trend_tags_cn=["低饱和粉彩趋势"],
                ),
                buzz=LegacyLocalizedText(en="x", cn="x"),
                brand=LegacyLocalizedText(en="x", cn="x"),
            ),
        )
        trend = _map_legacy_trend(lp)
        assert trend is not None
        assert trend.id == "trend_low_saturation_pastel"
        assert trend.tag == "Low-Saturation Pastel"
        assert trend.tag_cn == "低饱和粉彩趋势"
        assert trend.rationale is None
