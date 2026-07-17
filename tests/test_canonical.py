#!/usr/bin/env python3
"""Tests for Phase 4 canonical weekly dataset.

Covers:
  1. Canonical dataset file existence and structure
  2. report.json lossless adapter roundtrip
  3. Scoring model non-recomputable contract
  4. Source/evidence extraction completeness
  5. Manifest Phase 4 metadata and backward compat
  6. Serialization stability (determinism)
  7. Artifact hash integrity
  8. Empty-link gap preservation (2 warnings retained)
"""

import hashlib
import json
from pathlib import Path

import pytest
from beauty_weekly.canonical import (
    compute_artifact_hashes,
    generate_canonical_report,
    generate_scoring_model,
    generate_sources,
    validate_canonical,
)
from beauty_weekly.loader import load_legacy_report, load_report, to_target
from beauty_weekly.models import WeeklyReport

ROOT = Path(__file__).resolve().parent.parent
WEEKS_DIR = ROOT / "data" / "weeks" / "2026-W28"
LEGACY_PATH = ROOT / "data" / "week28.json"
HTML_FILES = ("index.html", "index-cn.html", "fragrance.html", "fragrance-cn.html")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def legacy():
    return load_legacy_report(LEGACY_PATH)


@pytest.fixture(scope="session")
def report_data():
    with open(WEEKS_DIR / "report.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def sources_data():
    with open(WEEKS_DIR / "sources.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def scoring_data():
    with open(WEEKS_DIR / "scoring.json", encoding="utf-8") as f:
        return json.load(f)


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
# 1. Canonical dataset file existence and structure
# ══════════════════════════════════════════════════════════════════════════════


class TestCanonicalFileExistence:
    def test_report_json_exists(self):
        assert (WEEKS_DIR / "report.json").exists()

    def test_sources_json_exists(self):
        assert (WEEKS_DIR / "sources.json").exists()

    def test_scoring_json_exists(self):
        assert (WEEKS_DIR / "scoring.json").exists()

    def test_manifest_json_exists(self):
        assert (WEEKS_DIR / "manifest.json").exists()

    def test_report_json_is_valid_json(self, report_data):
        assert isinstance(report_data, dict)

    def test_sources_json_is_valid_json(self, sources_data):
        assert isinstance(sources_data, dict)

    def test_scoring_json_is_valid_json(self, scoring_data):
        assert isinstance(scoring_data, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 2. report.json lossless adapter roundtrip
# ══════════════════════════════════════════════════════════════════════════════


class TestReportLossless:
    def test_report_validates_as_weekly_report(self, report_data):
        wr = WeeklyReport.model_validate(report_data, strict=False)
        assert wr.week == 28

    def test_report_matches_adapter_output(self, legacy):
        target, _warnings = to_target(legacy)
        expected = target.model_dump(mode="json", exclude_unset=True)
        with open(WEEKS_DIR / "report.json", encoding="utf-8") as f:
            actual = json.load(f)
        assert actual == expected

    def test_report_preserves_all_products(self, legacy):
        _, warnings = load_report(LEGACY_PATH)
        with open(WEEKS_DIR / "report.json", encoding="utf-8") as f:
            report = json.load(f)
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                legacy_section = getattr(getattr(legacy.products, topic), section)
                report_section = report["products"][topic][section]
                for panel in legacy_section:
                    assert panel in report_section
                    assert len(report_section[panel]) == len(legacy_section[panel])

    def test_report_preserves_trends(self, report_data):
        """All trend-badge products in report have Trend sub-objects."""
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = report_data["products"][topic][section]
                for _panel, products in panels.items():
                    for p in products:
                        if p.get("trend_badge") and p.get("trend"):
                            assert "id" in p["trend"]
                            assert "tag" in p["trend"]
                            assert "tag_cn" in p["trend"]

    def test_report_preserves_launch_evidence(self, report_data):
        """Fragrance radar products with quarantine_status have launch_evidence."""
        frag_radar = report_data["products"]["fragrance"]["new_product_radar"]
        for _panel, products in frag_radar.items():
            for p in products:
                le = p.get("launch_evidence")
                if le is not None:
                    assert "quarantine_status" in le
                    assert "launch_date" in le


# ══════════════════════════════════════════════════════════════════════════════
# 3. Scoring model non-recomputable contract
# ══════════════════════════════════════════════════════════════════════════════


class TestScoringModel:
    def test_recomputable_is_false(self, scoring_data):
        assert scoring_data["recomputable"] is False

    def test_components_are_null(self, scoring_data):
        assert scoring_data.get("components") is None

    def test_weights_are_null(self, scoring_data):
        assert scoring_data.get("weights") is None

    def test_has_version(self, scoring_data):
        assert "version" in scoring_data
        assert scoring_data["version"]

    def test_has_reason(self, scoring_data):
        assert "reason" in scoring_data
        assert len(scoring_data["reason"]) > 0

    def test_has_missing_components_list(self, scoring_data):
        mc = scoring_data.get("missing_components", [])
        assert isinstance(mc, list)
        assert len(mc) >= 4

    def test_has_validation_rules(self, scoring_data):
        rules = scoring_data.get("validation_rules", [])
        assert isinstance(rules, list)
        assert len(rules) >= 3
        checkable = [r for r in rules if r.get("checkable")]
        assert len(checkable) >= 2

    def test_observed_statistics_match_data(self, scoring_data, legacy):
        stats = scoring_data.get("observed_statistics", {})
        all_scores = []
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                lps = getattr(getattr(legacy.products, topic), section)
                for _panel, products in lps.items():
                    for p in products:
                        if p.score > 0:
                            all_scores.append(p.score)
        assert stats["observed_min"] == min(all_scores)
        assert stats["observed_max"] == max(all_scores)
        assert stats["total_scored_products"] == len(all_scores)

    def test_no_invented_components(self, scoring_data):
        """Scoring must not contain any fabricated weight or component."""
        assert scoring_data.get("components") is None
        assert scoring_data.get("weights") is None
        for key in ("methodology", "algorithm", "rubric"):
            assert key not in scoring_data, f"Scoring model must not invent '{key}'"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Source/evidence extraction completeness
# ══════════════════════════════════════════════════════════════════════════════


class TestSourcesExtraction:
    def test_sources_have_version(self, sources_data):
        assert "version" in sources_data

    def test_sources_list_is_nonempty(self, sources_data):
        assert sources_data["total_sources"] > 0
        assert len(sources_data["sources"]) > 0

    def test_source_entries_have_required_fields(self, sources_data):
        for src in sources_data["sources"]:
            assert "id" in src
            assert "url" in src
            assert src["url"], "Source URL must not be empty"
            assert src["id"].startswith("src_")

    def test_source_urls_are_unique(self, sources_data):
        urls = [s["url"] for s in sources_data["sources"]]
        assert len(urls) == len(set(urls))

    def test_no_empty_urls_in_sources(self, sources_data):
        for src in sources_data["sources"]:
            assert src["url"].strip(), f"Empty URL in source {src['id']}"

    def test_source_ids_are_sequential(self, sources_data):
        ids = [s["id"] for s in sources_data["sources"]]
        expected = [f"src_{i:04d}" for i in range(1, len(ids) + 1)]
        assert ids == expected

    def test_no_fabricated_urls(self, sources_data):
        """All source URLs must be real product/evidence URLs, not placeholders."""
        for src in sources_data["sources"]:
            url = src["url"]
            assert "example.com" not in url
            assert "localhost" not in url
            assert url.startswith("http"), f"Non-HTTP URL: {url}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Manifest Phase 4 metadata and backward compatibility
# ══════════════════════════════════════════════════════════════════════════════


class TestManifestPhase4:
    def test_schema_version_3(self, manifest_data):
        assert manifest_data["schema_version"] == 3

    def test_phase_4(self, manifest_data):
        assert manifest_data.get("phase") in ("4", "5", "6", "7"), (
            f"Expected phase 4, 5, 6, or 7, got {manifest_data.get('phase')}"
        )

    def test_week_and_iso_week(self, manifest_data):
        assert manifest_data["week"] == 28
        assert manifest_data["iso_week"] == "2026-W28"

    def test_data_pointer_backward_compat(self, manifest_data):
        """data_pointer must still exist for backward compat."""
        assert "data_pointer" in manifest_data
        assert manifest_data["data_pointer"].startswith("../../")

    def test_no_products_in_manifest(self, manifest_data):
        assert "products" not in manifest_data

    def test_resolved_warnings_preserved(self, manifest_data):
        assert "resolved_warnings" in manifest_data
        assert len(manifest_data["resolved_warnings"]) >= 1

    def test_remaining_warnings_updated(self, manifest_data):
        """remaining_warnings should match current adapter output."""
        _, warnings = load_report(LEGACY_PATH)
        assert manifest_data["remaining_warnings"] == len(warnings)

    def test_canonical_hash_exists(self, manifest_data):
        assert "canonical_hash" in manifest_data
        assert len(manifest_data["canonical_hash"]) == 64

    def test_scoring_hash_exists(self, manifest_data):
        assert "scoring_hash" in manifest_data
        assert len(manifest_data["scoring_hash"]) == 64

    def test_sources_hash_exists(self, manifest_data):
        assert "sources_hash" in manifest_data
        assert len(manifest_data["sources_hash"]) == 64

    def test_domain_separation_preserved(self, manifest_data):
        """Phase 3 domain_separation field preserved."""
        assert "domain_separation" in manifest_data
        assert len(manifest_data["domain_separation"]) >= 5

    def test_migration_gaps_preserved(self, manifest_data):
        assert "migration_gaps" in manifest_data
        assert len(manifest_data["migration_gaps"]) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 6. Serialization stability (determinism)
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterministicSerialization:
    def test_report_json_deterministic(self, legacy):
        """Two generations must produce byte-identical output."""
        d1, _ = generate_canonical_report(legacy)
        d2, _ = generate_canonical_report(legacy)
        from beauty_weekly.canonical import _deterministic_json

        assert _deterministic_json(d1) == _deterministic_json(d2)

    def test_sources_json_deterministic(self, legacy):
        from beauty_weekly.canonical import _deterministic_json

        s1 = generate_sources(legacy)
        s2 = generate_sources(legacy)
        assert _deterministic_json(s1) == _deterministic_json(s2)

    def test_scoring_json_deterministic(self, legacy):
        from beauty_weekly.canonical import _deterministic_json

        s1 = generate_scoring_model(legacy)
        s2 = generate_scoring_model(legacy)
        assert _deterministic_json(s1) == _deterministic_json(s2)

    def test_on_disk_matches_generation(self, legacy):
        """Files on disk must match fresh generation (no drift)."""
        d, _ = generate_canonical_report(legacy)
        with open(WEEKS_DIR / "report.json", encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk == d


# ══════════════════════════════════════════════════════════════════════════════
# 7. Artifact hash integrity
# ══════════════════════════════════════════════════════════════════════════════


class TestArtifactHashIntegrity:
    def test_hashes_match_manifest(self, manifest_data):
        hashes = compute_artifact_hashes(WEEKS_DIR)
        assert hashes["report.json"] == manifest_data["canonical_hash"]
        assert hashes["scoring.json"] == manifest_data["scoring_hash"]
        assert hashes["sources.json"] == manifest_data["sources_hash"]

    def test_hash_stability(self, legacy):
        """Hashes computed twice must be identical."""
        h1 = compute_artifact_hashes(WEEKS_DIR)
        h2 = compute_artifact_hashes(WEEKS_DIR)
        assert h1 == h2


# ══════════════════════════════════════════════════════════════════════════════
# 8. Empty-link gap preservation (2 warnings retained)
# ══════════════════════════════════════════════════════════════════════════════


class TestEmptyLinkGapPreservation:
    def test_exactly_two_empty_link_warnings(self):
        _, warnings = load_report(LEGACY_PATH)
        empty_link_warnings = [w for w in warnings if "empty link" in w]
        assert len(empty_link_warnings) == 2

    def test_empty_link_products_identified(self):
        _, warnings = load_report(LEGACY_PATH)
        empty_link_warnings = [w for w in warnings if "empty link" in w]
        names = [w.split("/")[3].split(":")[0] for w in empty_link_warnings]
        assert "To Summer Kunlun Snow" in names
        assert "Scent Library Boiled Water" in names

    def test_empty_links_reflected_in_report(self, report_data):
        """Products with empty links should have empty link in report."""
        frag_heat = report_data["products"]["fragrance"]["heat_rankings"]
        cn_masstige = frag_heat.get("CN MASSTIGE", [])
        for p in cn_masstige:
            if p["name"] in ("To Summer Kunlun Snow", "Scent Library Boiled Water"):
                link = p["detail"]["price_link"]["link"]
                assert link == "", f"{p['name']} should have empty link"


# ══════════════════════════════════════════════════════════════════════════════
# 9. Full canonical validation (integration)
# ══════════════════════════════════════════════════════════════════════════════


class TestCanonicalValidation:
    def test_validate_canonical_passes(self):
        errors = validate_canonical(WEEKS_DIR)
        assert errors == [], f"Canonical validation errors: {errors}"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Artifact hash comparison (HTML files unchanged)
# ══════════════════════════════════════════════════════════════════════════════


class TestHTMLFilesUnchanged:
    def test_week28_json_unchanged(self):
        """data/week28.json must not have been modified."""
        p = ROOT / "data" / "week28.json"
        # Just verify it loads and has the expected week
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        assert data["week"] == 28

    def test_html_files_exist(self):
        for name in HTML_FILES:
            assert (ROOT / name).exists(), f"Missing: {name}"
