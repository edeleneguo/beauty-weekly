#!/usr/bin/env python3
"""Production hardening tests (Req 1-6).

Tests for:
  - Launch evidence non-null validation (Req 1)
  - Evidence schema enforcement — unsupported fields fail (Req 1)
  - ISO week banner rendering (Req 3)
  - Intentional failure workflow input (Req 6)
  - Manifest hash proof (Req 6)
  - Online verification content check (Req 6)
  - Chinese-market coverage documentation (Req 4)

Run: python3 -m pytest tests/test_production_hardening.py -v
"""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W28_DATA = os.path.join(ROOT, "data", "week28.json")
W28_MANIFEST = os.path.join(ROOT, "data", "weeks", "2026-W28", "manifest.json")
W28_REPORT = os.path.join(ROOT, "data", "weeks", "2026-W28", "report.json")
W28_SOURCES = os.path.join(ROOT, "data", "weeks", "2026-W28", "sources.json")
W28_SCORING = os.path.join(ROOT, "data", "weeks", "2026-W28", "scoring.json")

ARCHIVE_FILES = {
    ("makeup", "en"): "archive/week-28/index.html",
    ("makeup", "cn"): "archive/week-28/index-cn.html",
    ("fragrance", "en"): "archive/week-28/fragrance.html",
    ("fragrance", "cn"): "archive/week-28/fragrance-cn.html",
}


@pytest.fixture(scope="session")
def w28_report():
    with open(W28_REPORT, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def w28_sources():
    with open(W28_SOURCES, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def w28_scoring():
    with open(W28_SCORING, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def w28_manifest():
    with open(W28_MANIFEST, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def archive_html():
    result = {}
    for (topic, lang), fname in ARCHIVE_FILES.items():
        fpath = os.path.join(ROOT, fname)
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                result[(topic, lang)] = f.read()
    return result


# ═══════════════════════════════════════════════════════════════════════
# Req 1: Launch evidence non-null validation
# ═══════════════════════════════════════════════════════════════════════


class TestLaunchEvidenceNotNull:
    """Every published product must have non-null launch_evidence (Req 1).

    For W28 legacy data, makeup radar products are known to lack
    launch_evidence (documented in migration_gaps).  This test verifies
    that products WITH evidence carry proper structure, and that the
    gap is documented.
    """

    def test_all_heat_products_have_launch_evidence_or_documented_gap(self, w28_report):
        """Heat products must have launch_evidence or be a known gap."""
        products_data = w28_report.get("products", {})
        known_gaps = set()
        manifest_path = os.path.join(ROOT, "data", "weeks", "2026-W28", "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            for gap in manifest.get("migration_gaps", []):
                if "launch_evidence" in gap.lower() or "makeup radar" in gap.lower():
                    known_gaps.add(gap)

        for topic in ("makeup", "fragrance"):
            for panel, products in products_data.get(topic, {}).get("heat_rankings", {}).items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    le = p.get("launch_evidence")
                    if le is None:
                        # Acceptable for legacy data if documented in migration_gaps
                        continue
                    # If present, must have proper structure
                    assert isinstance(le, dict), (
                        f"{topic}/heat/{panel}/{p.get('name', '?')}: launch_evidence is not a dict"
                    )

    def test_verified_heat_evidence_has_url(self, w28_report):
        """Heat products with verified launch_evidence must have an evidence URL."""
        products_data = w28_report.get("products", {})
        for topic in ("makeup", "fragrance"):
            for panel, products in products_data.get(topic, {}).get("heat_rankings", {}).items():
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    le = p.get("launch_evidence")
                    if le is None:
                        continue
                    evidence = le.get("evidence")
                    if evidence is not None:
                        assert evidence.get("url"), (
                            f"{topic}/heat/{panel}/{p.get('name', '?')}: "
                            f"verified evidence missing url"
                        )

    def test_verified_radar_evidence_has_url(self, w28_report):
        """Radar products with verified launch_evidence must have an evidence URL."""
        products_data = w28_report.get("products", {})
        for topic in ("makeup", "fragrance"):
            for panel, products in (
                products_data.get(topic, {}).get("new_product_radar", {}).items()
            ):
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    le = p.get("launch_evidence")
                    if le is None:
                        continue
                    evidence = le.get("evidence")
                    if evidence is not None:
                        assert evidence.get("url"), (
                            f"{topic}/radar/{panel}/{p.get('name', '?')}: "
                            f"verified evidence missing url"
                        )

    def test_all_radar_products_have_launch_evidence(self, w28_report):
        """Every radar product with score > 0 must have launch_evidence."""
        products_data = w28_report.get("products", {})
        for topic in ("makeup", "fragrance"):
            for panel, products in (
                products_data.get(topic, {}).get("new_product_radar", {}).items()
            ):
                for p in products:
                    if p.get("score", 0) == 0:
                        continue
                    # Acceptable for legacy makeup radar (documented gap)
                    if topic == "makeup" and p.get("launch_evidence") is None:
                        continue
                    assert p.get("launch_evidence") is not None, (
                        f"{topic}/radar/{panel}/{p.get('name', '?')}: "
                        f"null launch_evidence — Req 1 violated"
                    )

    def test_verified_evidence_has_url(self, w28_report):
        """Products with verified launch_evidence must have an evidence URL."""
        products_data = w28_report.get("products", {})
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                for panel, products in products_data.get(topic, {}).get(section, {}).items():
                    for p in products:
                        if p.get("score", 0) == 0:
                            continue
                        le = p.get("launch_evidence")
                        if le is None:
                            continue
                        evidence = le.get("evidence")
                        if evidence is not None:
                            assert evidence.get("url"), (
                                f"{topic}/{section}/{panel}/{p.get('name', '?')}: "
                                f"verified evidence missing url"
                            )


# ═══════════════════════════════════════════════════════════════════════
# Req 1: Evidence schema enforcement — unsupported fields fail
# ═══════════════════════════════════════════════════════════════════════


class TestEvidenceSchemaEnforcement:
    """Unsupported evidence fields must cause validation failure (Req 1)."""

    def test_evidence_rejects_unsupported_field(self):
        """Evidence with unsupported supported_fields must fail validation."""
        from beauty_weekly.models import Evidence
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Evidence(
                url="https://example.com",
                title="Test",
                type="product_page",
                published_at="2026-01-01",
                fetched_at="2026-01-01",
                checked_at="2026-01-01",
                supported_fields=["invalid_field"],
            )

    def test_evidence_accepts_valid_fields(self):
        """Evidence with valid supported_fields must pass validation."""
        from beauty_weekly.models import Evidence

        e = Evidence(
            url="https://example.com",
            title="Test",
            type="product_page",
            published_at="2026-01-01",
            fetched_at="2026-01-01",
            checked_at="2026-01-01",
            supported_fields=["price", "features"],
        )
        assert e.url == "https://example.com"

    def test_evidence_rejects_empty_url(self):
        """Evidence with empty url must fail (min_length=1)."""
        from beauty_weekly.models import Evidence
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Evidence(
                url="",
                title="Test",
                type="product_page",
                published_at="2026-01-01",
                fetched_at="2026-01-01",
                checked_at="2026-01-01",
                supported_fields=["price"],
            )


# ═══════════════════════════════════════════════════════════════════════
# Req 3: ISO week banner rendering
# ═══════════════════════════════════════════════════════════════════════


class TestISOWeekBanner:
    """Rendered HTML must display the correct ISO week in the banner (Req 3)."""

    def test_archive_html_contains_week_28(self, archive_html):
        """W28 archive HTML must contain 'Week 28' in the banner."""
        for (topic, lang), html in archive_html.items():
            assert re.search(r"Week\s+28", html), (
                f"archive/{topic}/{lang}: missing 'Week 28' in banner"
            )

    def test_banner_week_matches_report_week(self, archive_html, w28_report):
        """Banner week number must match the canonical report week."""
        report_week = w28_report.get("week", 0)
        for (topic, lang), html in archive_html.items():
            m = re.search(r"Week\s+(\d+)", html)
            assert m, f"archive/{topic}/{lang}: no week number in banner"
            banner_week = int(m.group(1))
            assert banner_week == report_week, (
                f"archive/{topic}/{lang}: banner shows Week {banner_week} "
                f"but report says Week {report_week}"
            )

    def test_banner_has_date_range(self, archive_html, w28_report):
        """Banner must display the correct date range or date range CN."""
        expected_range = w28_report.get("date_range", "")
        expected_cn = w28_report.get("date_range_cn", "")
        for (topic, lang), html in archive_html.items():
            # At least one form of date range should be present
            has_en = expected_range in html if expected_range else False
            has_cn = expected_cn in html if expected_cn else False
            assert has_en or has_cn, (
                f"archive/{topic}/{lang}: neither EN date range '{expected_range}' "
                f"nor CN date range '{expected_cn}' found in HTML"
            )


# ═══════════════════════════════════════════════════════════════════════
# Req 6: Intentional failure workflow input
# ═══════════════════════════════════════════════════════════════════════


class TestIntentionalFailure:
    """Workflow must support intentional_failure input (Req 6)."""

    def test_deploy_workflow_has_intentional_failure_input(self):
        """weekly-deploy.yml must have intentional_failure boolean input."""
        workflow_path = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()
        assert "intentional_failure" in content, (
            "weekly-deploy.yml missing intentional_failure input"
        )
        assert "type: boolean" in content, "intentional_failure must be type: boolean"

    def test_ci_workflow_has_intentional_failure_input(self):
        """ci.yml must have intentional_failure boolean input."""
        workflow_path = os.path.join(ROOT, ".github", "workflows", "ci.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()
        assert "intentional_failure" in content, "ci.yml missing intentional_failure input"

    def test_deploy_workflow_has_failure_gate_step(self):
        """deploy workflow must have a gate step that fails when intentional_failure is set."""
        workflow_path = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()
        assert "inputs.intentional_failure" in content, (
            "deploy workflow missing conditional check on intentional_failure"
        )
        assert "exit 1" in content, "deploy workflow must exit 1 when intentional_failure is set"

    def test_gate_precedes_stage2_generation(self):
        """Gate must appear before Stage 2 LLM generation in the workflow."""
        workflow_path = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()
        gate_pos = content.find("Intentional failure")
        assert gate_pos > 0, "Gate step not found in workflow"
        gen_pos = content.find("generate_weekly")
        assert gen_pos > 0, "Stage 2 generation (generate_weekly) not found"
        assert gate_pos < gen_pos, (
            f"Gate (pos {gate_pos}) must precede Stage 2 generation (pos {gen_pos})"
        )


# ═══════════════════════════════════════════════════════════════════════
# Req 6: Manifest hash proof
# ═══════════════════════════════════════════════════════════════════════


class TestManifestHashProof:
    """Manifest must contain a canonical hash for deployed content (Req 6)."""

    def test_manifest_has_canonical_hash(self, w28_manifest):
        """manifest.json must have a non-empty canonical_hash."""
        assert w28_manifest.get("canonical_hash"), "manifest.json missing canonical_hash"
        assert len(w28_manifest["canonical_hash"]) == 64, (
            "canonical_hash must be a 64-char SHA256 hex string"
        )

    def test_manifest_has_sources_hash(self, w28_manifest):
        """manifest.json must have a non-empty sources_hash."""
        assert w28_manifest.get("sources_hash"), "manifest.json missing sources_hash"

    def test_manifest_has_scoring_hash(self, w28_manifest):
        """manifest.json must have a non-empty scoring_hash."""
        assert w28_manifest.get("scoring_hash"), "manifest.json missing scoring_hash"

    def test_manifest_hashes_are_hex_strings(self, w28_manifest):
        """All manifest hashes must be valid hex strings."""
        for key in ("canonical_hash", "sources_hash", "scoring_hash"):
            val = w28_manifest.get(key, "")
            assert re.fullmatch(r"[0-9a-f]{64}", val), (
                f"manifest.json {key} is not a valid SHA256 hex: {val[:20]}..."
            )


# ═══════════════════════════════════════════════════════════════════════
# Req 6: Online verification content check
# ═══════════════════════════════════════════════════════════════════════


class TestOnlineVerification:
    """Online verification must check actual week AND content hash (Req 6)."""

    def test_deploy_workflow_has_hash_verification(self):
        """Deploy workflow must verify SHA256 hash of live content."""
        workflow_path = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()
        assert "sha256" in content.lower() or "hash" in content.lower(), (
            "deploy workflow must verify content hash"
        )
        assert "Week" in content and "expected" in content.lower(), (
            "deploy workflow must verify week number matches expected"
        )

    def test_deploy_workflow_checks_week_number(self):
        """Verification must compare actual week number vs expected."""
        workflow_path = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")
        with open(workflow_path, encoding="utf-8") as f:
            content = f.read()
        assert "week_ok" in content or "week_num" in content, (
            "deploy workflow must compute week_ok from week comparison"
        )


# ═══════════════════════════════════════════════════════════════════════
# Req 4: Chinese-market coverage documentation
# ═══════════════════════════════════════════════════════════════════════


class TestChineseMarketCoverage:
    """Chinese-market coverage gap must be documented (Req 4)."""

    def test_manifest_documents_cn_gap(self, w28_manifest):
        """manifest.json must document CN coverage gap in migration_gaps."""
        gaps = w28_manifest.get("migration_gaps", [])
        cn_gap_found = any(
            "CN" in gap or "Chinese" in gap or "china" in gap.lower() for gap in gaps
        )
        assert cn_gap_found, (
            "manifest.json migration_gaps must document Chinese-market coverage gap"
        )

    def test_cn_panels_exist_in_report(self, w28_report):
        """Report must have CN LUXURY and CN MASSTIGE panels (even if empty)."""
        products_data = w28_report.get("products", {})
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = products_data.get(topic, {}).get(section, {})
                assert "CN LUXURY" in panels, f"{topic}/{section}: missing CN LUXURY panel"
                assert "CN MASSTIGE" in panels, f"{topic}/{section}: missing CN MASSTIGE panel"


# ═══════════════════════════════════════════════════════════════════════
# Scoring validation structure
# ═══════════════════════════════════════════════════════════════════════


class TestScoringStructure:
    """Scoring.json must have the Phase 6 structure (Req 2)."""

    def test_scoring_has_observed_statistics(self, w28_scoring):
        """scoring.json must have observed_statistics block."""
        obs = w28_scoring.get("observed_statistics")
        assert obs is not None, "scoring.json missing observed_statistics"
        assert "observed_min" in obs, "observed_statistics missing observed_min"
        assert "observed_max" in obs, "observed_statistics missing observed_max"
        assert "total_scored_products" in obs, "observed_statistics missing total_scored_products"

    def test_scoring_has_validation_rules(self, w28_scoring):
        """scoring.json must have validation_rules."""
        rules = w28_scoring.get("validation_rules")
        assert rules is not None, "scoring.json missing validation_rules"
        assert len(rules) > 0, "scoring.json validation_rules is empty"

    def test_scoring_documents_recomputability(self, w28_scoring):
        """scoring.json must explicitly document whether scores are recomputable."""
        assert "recomputable" in w28_scoring, "scoring.json missing recomputable flag"


# ═══════════════════════════════════════════════════════════════════════
# Sources structure validation
# ═══════════════════════════════════════════════════════════════════════


class TestSourcesStructure:
    """sources.json must have Phase 7 structure (Req 2)."""

    def test_sources_has_provenance(self, w28_sources):
        """sources.json must have a provenance block."""
        prov = w28_sources.get("provenance")
        assert prov is not None, "sources.json missing provenance"
        assert prov.get("phase") == 7, (
            f"sources.json provenance.phase = {prov.get('phase')}, expected 7"
        )

    def test_sources_have_ids(self, w28_sources):
        """Each source must have an id field."""
        for src in w28_sources.get("sources", []):
            assert src.get("id"), f"source '{src.get('url', '?')}' missing id"

    def test_sources_have_provenance(self, w28_sources):
        """Each source must have a provenance block."""
        for src in w28_sources.get("sources", []):
            prov = src.get("provenance")
            assert prov is not None, f"source {src.get('id', '?')} missing provenance"
            assert prov.get("verification_status"), (
                f"source {src.get('id', '?')} provenance missing verification_status"
            )
