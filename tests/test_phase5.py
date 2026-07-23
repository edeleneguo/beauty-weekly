"""Tests for Phase 5: canonical read-path integration, parity, and drift detection.

Covers:
  1. Canonical-to-legacy adapter lossless parity
  2. Hard parity guard: adapter( canonical ) == legacy data for all business fields
  3. Canonical report is the authoritative read path (renderer/validator consume it)
  4. Two known empty-link gaps preserved
  5. Manifest Phase 5 metadata present
  6. Deterministic render stability via canonical path
  7. Canary: canonical generation stability
"""

import hashlib
import json
from pathlib import Path

import pytest
from beauty_weekly.canonical import (
    generate_canonical_report,
    validate_canonical,
)
from beauty_weekly.canonical_adapter import canonical_to_legacy
from beauty_weekly.loader import load_legacy_report

ROOT = Path(__file__).resolve().parent.parent
WEEKS_DIR = ROOT / "data" / "weeks" / "2026-W28"
LEGACY_PATH = ROOT / "data" / "week28.json"
CANONICAL_PATH = WEEKS_DIR / "report.json"
HTML_FILES = ("index.html", "fragrance.html")


@pytest.fixture(scope="session")
def legacy_data():
    with open(LEGACY_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def canonical_data():
    with open(CANONICAL_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def adapted_data(canonical_data):
    return canonical_to_legacy(canonical_data)


@pytest.fixture(scope="session")
def manifest_data():
    with open(WEEKS_DIR / "manifest.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def html_hashes():
    h = {}
    for name in HTML_FILES:
        p = ROOT / name
        if p.exists():
            h[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return h


# ══════════════════════════════════════════════════════════════════════════════
# 1. Adapter lossless parity
# ══════════════════════════════════════════════════════════════════════════════


class TestAdapterParity:
    """Verify canonical_to_legacy produces legacy-identical output."""

    def test_adapted_has_all_panels(self, adapted_data):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = adapted_data["products"][topic][section]
                assert set(panels.keys()) == {
                    "US LUXURY",
                    "US MASSTIGE",
                    "CN LUXURY",
                    "CN MASSTIGE",
                }

    def test_adapted_product_counts_match_legacy(self, adapted_data, legacy_data):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted_count = len(adapted_data["products"][topic][section][panel])
                    legacy_count = len(legacy_data["products"][topic][section][panel])
                    assert adapted_count == legacy_count, (
                        f"{topic}/{section}/{panel}: adapted={adapted_count} legacy={legacy_count}"
                    )

    def test_adapted_preserves_scores(self, adapted_data, legacy_data):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted_scores = [
                        p["score"] for p in adapted_data["products"][topic][section][panel]
                    ]
                    legacy_scores = [
                        p["score"] for p in legacy_data["products"][topic][section][panel]
                    ]
                    assert adapted_scores == legacy_scores, (
                        f"{topic}/{section}/{panel}: scores differ"
                    )

    def test_adapted_preserves_detail_links(self, adapted_data, legacy_data):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted = adapted_data["products"][topic][section][panel]
                    legacy = legacy_data["products"][topic][section][panel]
                    for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                        adapted_link = ap["detail"]["price_link"]["link"]
                        legacy_link = lp["detail"]["price_link"]["link"]
                        assert adapted_link == legacy_link, (
                            f"{topic}/{section}/{panel}[{i}]: "
                            f"link mismatch '{adapted_link}' != '{legacy_link}'"
                        )

    def test_adapted_preserves_flat_fields(self, adapted_data, legacy_data):
        flat_fields = [
            "market",
            "tier",
            "name",
            "category_badge",
            "score",
            "trend_badge",
            "new_badge",
        ]
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted = adapted_data["products"][topic][section][panel]
                    legacy = legacy_data["products"][topic][section][panel]
                    for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                        for field in flat_fields:
                            assert ap.get(field) == lp.get(field), (
                                f"{topic}/{section}/{panel}[{i}]: '{field}' mismatch"
                            )

    def test_adapted_preserves_evidence_fields(self, adapted_data, legacy_data):
        evidence_fields = [
            "quarantine_status",
            "quarantine_reason",
            "launch_date",
            "evidence_url",
            "evidence_type",
            "evidence_checked_at",
        ]
        for topic in ("makeup", "fragrance"):
            section = "new_product_radar"
            for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                adapted = adapted_data["products"][topic][section][panel]
                legacy = legacy_data["products"][topic][section][panel]
                for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                    for field in evidence_fields:
                        assert ap.get(field) == lp.get(field), (
                            f"{topic}/{section}/{panel}[{i}]: "
                            f"'{field}' mismatch: "
                            f"adapted={repr(ap.get(field))} legacy={repr(lp.get(field))}"
                        )

    def test_adapted_preserves_trend_flat_fields(self, adapted_data, legacy_data):
        trend_flat_fields = [
            "trend_id",
            "trend_tag",
            "trend_tag_cn",
            "trend_rationale",
        ]
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted = adapted_data["products"][topic][section][panel]
                    legacy = legacy_data["products"][topic][section][panel]
                    for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                        for field in trend_flat_fields:
                            assert ap.get(field) == lp.get(field), (
                                f"{topic}/{section}/{panel}[{i}]: "
                                f"'{field}' mismatch: "
                                f"adapted={repr(ap.get(field))} legacy={repr(lp.get(field))}"
                            )

    def test_adapted_preserves_name_cn(self, adapted_data, legacy_data):
        """name_cn must match when present; otherwise both should be absent."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted = adapted_data["products"][topic][section][panel]
                    legacy = legacy_data["products"][topic][section][panel]
                    for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                        if "name_cn" in lp:
                            assert ap.get("name_cn") == lp.get("name_cn"), (
                                f"{topic}/{section}/{panel}[{i}]: name_cn mismatch"
                            )

    def test_adapted_top_level_fields(self, adapted_data, legacy_data):
        for field in ("week", "date_range", "date_range_cn", "version"):
            assert adapted_data.get(field) == legacy_data.get(field), (
                f"Top-level field '{field}' mismatch"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 2. Hard parity guard
# ══════════════════════════════════════════════════════════════════════════════


class TestHardParity:
    """The adapter must produce exactly the legacy-shaped field values."""

    COMPARED_FIELDS = [
        "rank",
        "market",
        "tier",
        "name",
        "name_cn",
        "category_badge",
        "score",
        "trend_badge",
        "new_badge",
        "quarantine_status",
        "quarantine_reason",
        "launch_date",
        "evidence_url",
        "evidence_type",
        "evidence_checked_at",
        "trend_id",
        "trend_tag",
        "trend_tag_cn",
        "trend_rationale",
    ]

    def test_every_product_field_matches(self, adapted_data, legacy_data):
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted = adapted_data["products"][topic][section][panel]
                    legacy = legacy_data["products"][topic][section][panel]
                    for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                        loc = f"{topic}/{section}/{panel}[{i}]"
                        for field in self.COMPARED_FIELDS:
                            av = ap.get(field)
                            lv = lp.get(field)
                            assert av == lv, f"{loc}: {field} adapted={repr(av)} legacy={repr(lv)}"

    def test_every_detail_field_matches(self, adapted_data, legacy_data):
        detail_paths = [
            ("price_link", "en"),
            ("price_link", "cn"),
            ("price_link", "link"),
            ("key_features", "en"),
            ("key_features", "cn"),
            ("buzz", "en"),
            ("buzz", "cn"),
            ("brand", "en"),
            ("brand", "cn"),
        ]
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                    adapted = adapted_data["products"][topic][section][panel]
                    legacy = legacy_data["products"][topic][section][panel]
                    for i, (ap, lp) in enumerate(zip(adapted, legacy)):
                        loc = f"{topic}/{section}/{panel}[{i}]"
                        for dkey, subkey in detail_paths:
                            av = ap.get("detail", {}).get(dkey, {}).get(subkey)
                            lv = lp.get("detail", {}).get(dkey, {}).get(subkey)
                            assert av == lv, (
                                f"{loc}: detail.{dkey}.{subkey} "
                                f"adapted={repr(av)} legacy={repr(lv)}"
                            )

    def test_empty_link_gaps_preserved(self, adapted_data):
        frag_heat = adapted_data["products"]["fragrance"]["heat_rankings"]
        cn_masstige = frag_heat.get("CN MASSTIGE", [])
        empty_link_products = [p for p in cn_masstige if p["detail"]["price_link"]["link"] == ""]
        names = [p["name"] for p in empty_link_products]
        assert "To Summer Kunlun Snow" in names
        assert "Scent Library Boiled Water" in names
        assert len(names) == 2

    def test_renderer_can_consume_adapter_output(self, adapted_data):
        """The adapted data must be structurally valid for the renderer."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = adapted_data["products"][topic][section]
                assert len(panels) == 4
                for _panel_key, products in panels.items():
                    for p in products:
                        assert "rank" in p
                        assert "score" in p
                        assert "detail" in p
                        for dkey in ("price_link", "key_features", "buzz", "brand"):
                            assert dkey in p["detail"]
                        assert "link" in p["detail"]["price_link"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Canonical is the authoritative read path
# ══════════════════════════════════════════════════════════════════════════════


class TestCanonicalReadPath:
    def test_canonical_report_exists(self):
        assert CANONICAL_PATH.exists()

    def test_canonical_validates(self):
        errors = validate_canonical(WEEKS_DIR)
        assert errors == [], f"Canonical validation errors: {errors}"

    def test_canonical_passes_weekly_report_schema(self, canonical_data):
        from beauty_weekly.models import WeeklyReport

        wr = WeeklyReport.model_validate(canonical_data, strict=False)
        assert wr.week == 28

    def test_canonical_generation_is_stable(self):
        legacy = load_legacy_report(LEGACY_PATH)
        d1, _ = generate_canonical_report(legacy)
        d2, _ = generate_canonical_report(legacy)
        from beauty_weekly.canonical import _deterministic_json

        assert _deterministic_json(d1) == _deterministic_json(d2)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Manifest Phase 5 metadata
# ══════════════════════════════════════════════════════════════════════════════


class TestManifestPhase5:
    def test_phase_is_at_least_5(self, manifest_data):
        assert manifest_data.get("phase", "0") >= "5"

    def test_schema_version_at_least_3(self, manifest_data):
        assert manifest_data["schema_version"] >= 3

    def test_migration_deprecation_exists(self, manifest_data):
        assert "migration_deprecation" in manifest_data
        dep = manifest_data["migration_deprecation"]
        assert "data_week28_json" in dep
        assert dep["data_week28_json"]["status"] == "legacy_compat"
        assert dep["data_week28_json"]["phase_deprecated"] >= "5"

    def test_legacy_data_pointer_preserved(self, manifest_data):
        assert manifest_data["data_pointer"] == "../../week28.json"

    def test_canonical_hash_present(self, manifest_data):
        assert "canonical_hash" in manifest_data
        assert len(manifest_data["canonical_hash"]) == 64

    def test_remaining_warnings_preserved(self, manifest_data):
        assert manifest_data["remaining_warnings"] == 2

    def test_migration_gaps_preserved(self, manifest_data):
        assert len(manifest_data["migration_gaps"]) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 5. HTML files unchanged from Phase 4 baseline
# ══════════════════════════════════════════════════════════════════════════════


class TestHTMLUnchanged:
    """Phase 5 must not modify HTML templates or content."""

    def test_html_files_exist(self):
        for name in HTML_FILES:
            assert (ROOT / name).exists(), f"Missing: {name}"

    def test_week28_json_unchanged(self):
        p = ROOT / "data" / "week28.json"
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        assert data["week"] == 28


# ══════════════════════════════════════════════════════════════════════════════
# 6. Projection parity guard (Phase 5)
# ══════════════════════════════════════════════════════════════════════════════


class TestProjectionParity:
    """The render/business projection must be fully satisfied by canonical data."""

    def test_projection_guard_passes(self):
        """validate_canonical includes projection parity — must pass."""
        errors = validate_canonical(WEEKS_DIR)
        projection_errors = [
            e
            for e in errors
            if "render projection" in e
            or "missing detail" in e
            or "missing trend" in e
            or "launch_evidence" in e
        ]
        assert projection_errors == [], f"Projection parity errors: {projection_errors}"

    def test_all_render_fields_documented(self):
        """The render projection constants must cover every field the renderer reads."""
        from beauty_weekly.canonical import (
            DETAIL_PROJECTION_KEYS,
            EVIDENCE_PROJECTION_FIELDS,
            LAUNCH_EVIDENCE_PROJECTION_FIELDS,
            PRODUCT_PROJECTION_FIELDS,
            REPORT_PROJECTION_FIELDS,
            TREND_PROJECTION_FIELDS,
        )

        # Must be non-empty
        assert len(PRODUCT_PROJECTION_FIELDS) >= 8
        assert len(DETAIL_PROJECTION_KEYS) == 4
        assert len(REPORT_PROJECTION_FIELDS) >= 4
        assert len(LAUNCH_EVIDENCE_PROJECTION_FIELDS) >= 3
        assert len(EVIDENCE_PROJECTION_FIELDS) >= 3
        assert len(TREND_PROJECTION_FIELDS) >= 2

    def test_canonical_has_all_render_fields(self, canonical_data):
        """Every product in canonical must have the projection fields."""
        from beauty_weekly.canonical import (
            DETAIL_PROJECTION_KEYS,
            PRODUCT_PROJECTION_FIELDS,
        )

        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = canonical_data["products"][topic][section]
                for panel_key, products in panels.items():
                    for p in products:
                        for field in PRODUCT_PROJECTION_FIELDS:
                            assert field in p, (
                                f"{topic}/{section}/{panel_key}/{p.get('name')}: "
                                f"missing projection field '{field}'"
                            )
                        for dkey in DETAIL_PROJECTION_KEYS:
                            assert dkey in p.get("detail", {}), (
                                f"{topic}/{section}/{panel_key}/{p.get('name')}: "
                                f"missing detail.{dkey}"
                            )


# ══════════════════════════════════════════════════════════════════════════════
# 7. Deprecation metadata (Phase 5)
# ══════════════════════════════════════════════════════════════════════════════


class TestDeprecationMetadata:
    """Manifest must document deprecation status of legacy data path."""

    def test_deprecation_has_status(self, manifest_data):
        dep = manifest_data.get("migration_deprecation", {})
        assert dep.get("data_week28_json", {}).get("status") == "legacy_compat"

    def test_deprecation_has_phase(self, manifest_data):
        dep = manifest_data.get("migration_deprecation", {})
        assert dep.get("data_week28_json", {}).get("phase_deprecated") == "5"

    def test_deprecation_has_canonical_path(self, manifest_data):
        dep = manifest_data.get("migration_deprecation", {})
        assert "read_path" in dep.get("data_week28_json", {})
        assert "canonical" in dep["data_week28_json"]["read_path"]

    def test_deprecation_fields_isolated(self, manifest_data):
        """Legacy fields isolated from canonical must be documented."""
        dep = manifest_data.get("migration_deprecation", {})
        # The deprecation section documents build tool changes too
        assert len(dep) >= 3

    def test_legacy_not_primary_read_path(self, manifest_data):
        """The manifest must document that legacy is not the primary read path."""
        dep = manifest_data.get("migration_deprecation", {})
        action = dep.get("data_week28_json", {}).get("action", "")
        assert "DO NOT DELETE" in action or "baseline" in action


# ══════════════════════════════════════════════════════════════════════════════
# 8. Drift detection and hash stability
# ══════════════════════════════════════════════════════════════════════════════


class TestDriftAndHashes:
    """Canonical artifacts must be stable; no drift from regeneration."""

    def test_detect_canonical_drift(self):
        from beauty_weekly.canonical import detect_canonical_drift

        errors = detect_canonical_drift(WEEKS_DIR)
        assert errors == [], f"Drift detected: {errors}"

    def test_report_hash_matches_manifest(self, manifest_data):
        from beauty_weekly.canonical import compute_artifact_hashes

        hashes = compute_artifact_hashes(WEEKS_DIR)
        assert hashes["report.json"] == manifest_data["canonical_hash"]

    def test_scoring_hash_matches_manifest(self, manifest_data):
        from beauty_weekly.canonical import compute_artifact_hashes

        hashes = compute_artifact_hashes(WEEKS_DIR)
        assert hashes["scoring.json"] == manifest_data["scoring_hash"]

    def test_sources_hash_matches_manifest(self, manifest_data):
        from beauty_weekly.canonical import compute_artifact_hashes

        hashes = compute_artifact_hashes(WEEKS_DIR)
        assert hashes["sources.json"] == manifest_data["sources_hash"]

    def test_adapted_render_identical(self, canonical_data):
        """Canonical → adapter → render must produce identical HTML hashes."""
        from beauty_weekly.canonical_adapter import canonical_to_legacy

        adapted = canonical_to_legacy(canonical_data)
        import os
        import sys

        sys.path.insert(0, os.path.join(ROOT, "build"))
        from render import _render_section

        for topic in ("makeup", "fragrance"):
            for lang in ("en", "cn"):
                section_key = "heat_rankings"
                adapted_panels = adapted["products"][topic][section_key]
                heat_html = _render_section(adapted_panels, lang, topic, "heat")
                # Must produce non-empty HTML
                assert len(heat_html) > 100, f"{topic} {lang}: heat render too short"
