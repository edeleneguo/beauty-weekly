"""Tests for Phase 6: versioned scoring policy and recomputation engine.

Covers:
  1. Scoring policy constants and component definitions
  2. Deterministic score computation
  3. Score bounds and rounding
  4. Error handling for missing/out-of-range components
  5. Scoring record construction with provenance
  6. scoring.json schema validation (recomputable and non-recomputable)
  7. Score consistency validation against report data
  8. Week 28 historical record preserved as non-recomputable
  9. Backward compatibility with v1 scoring.json
 10. Policy block construction
"""

import hashlib
import json
from pathlib import Path

import pytest
from beauty_weekly.scoring import (
    COMPONENT_IDS,
    ROUNDING,
    SCORE_MAX,
    SCORE_MIN,
    SCORING_COMPONENTS,
    SCORING_POLICY_VERSION,
    SCORING_SCHEMA,
    TOTAL_WEIGHT,
    WEIGHTS_MAP,
    build_policy_block,
    build_scoring_record,
    compute_score,
    validate_recomputed_scoring,
    validate_scoring_json,
)

ROOT = Path(__file__).resolve().parent.parent
WEEKS_DIR = ROOT / "data" / "weeks" / "2026-W28"
LEGACY_PATH = ROOT / "data" / "week28.json"
HTML_FILES = ("index.html", "fragrance.html")


@pytest.fixture(scope="session")
def scoring_data():
    with open(WEEKS_DIR / "scoring.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def report_data():
    with open(WEEKS_DIR / "report.json", encoding="utf-8") as f:
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
# 1. Policy constants and component definitions
# ══════════════════════════════════════════════════════════════════════════════


class TestPolicyConstants:
    def test_policy_version_is_string(self):
        assert isinstance(SCORING_POLICY_VERSION, str)
        assert SCORING_POLICY_VERSION == "2.0.0"

    def test_scoring_schema(self):
        assert SCORING_SCHEMA == "beauty-weekly-scoring-v2"

    def test_score_bounds(self):
        assert SCORE_MIN == 0
        assert SCORE_MAX == 100

    def test_rounding_mode(self):
        assert ROUNDING == "nearest_integer"

    def test_weights_sum_to_one(self):
        assert abs(TOTAL_WEIGHT - 1.0) < 1e-9

    def test_components_have_required_fields(self):
        required = {"id", "label", "weight", "source_field", "bounds", "description"}
        for comp in SCORING_COMPONENTS:
            for field in required:
                assert field in comp, f"Component {comp.get('id')} missing {field}"

    def test_component_weights_positive(self):
        for comp in SCORING_COMPONENTS:
            assert comp["weight"] > 0, f"Component {comp['id']} weight must be positive"
            assert comp["weight"] <= 1.0, f"Component {comp['id']} weight must be <= 1.0"

    def test_component_ids_unique(self):
        ids = [c["id"] for c in SCORING_COMPONENTS]
        assert len(ids) == len(set(ids))

    def test_component_bounds(self):
        for comp in SCORING_COMPONENTS:
            assert comp["bounds"]["min"] == 0
            assert comp["bounds"]["max"] == 100

    def test_weights_map_consistent(self):
        for comp in SCORING_COMPONENTS:
            assert WEIGHTS_MAP[comp["id"]] == comp["weight"]
        assert len(WEIGHTS_MAP) == len(SCORING_COMPONENTS)

    def test_component_ids_list(self):
        assert len(COMPONENT_IDS) == 4
        assert "social_engagement" in COMPONENT_IDS
        assert "sales_velocity" in COMPONENT_IDS
        assert "review_sentiment" in COMPONENT_IDS
        assert "trend_alignment" in COMPONENT_IDS


# ══════════════════════════════════════════════════════════════════════════════
# 2. Deterministic score computation
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterministicComputation:
    def test_all_100_yields_100(self):
        vals = {c["id"]: 100.0 for c in SCORING_COMPONENTS}
        assert compute_score(vals) == 100

    def test_all_0_yields_0(self):
        vals = {c["id"]: 0.0 for c in SCORING_COMPONENTS}
        assert compute_score(vals) == 0

    def test_all_50_yields_50(self):
        vals = {c["id"]: 50.0 for c in SCORING_COMPONENTS}
        assert compute_score(vals) == 50

    def test_deterministic_same_input_same_output(self):
        vals = {
            "social_engagement": 80.0,
            "sales_velocity": 70.0,
            "review_sentiment": 90.0,
            "trend_alignment": 60.0,
        }
        r1 = compute_score(vals)
        r2 = compute_score(vals)
        assert r1 == r2

    def test_integer_inputs(self):
        vals = {
            "social_engagement": 80,
            "sales_velocity": 70,
            "review_sentiment": 90,
            "trend_alignment": 60,
        }
        assert isinstance(compute_score(vals), int)

    def test_weighted_average_formula(self):
        vals = {
            "social_engagement": 100.0,
            "sales_velocity": 0.0,
            "review_sentiment": 0.0,
            "trend_alignment": 0.0,
        }
        expected = round(100 * 0.35)
        assert compute_score(vals) == expected

    def test_computation_uses_weighted_sum(self):
        """Weighted components produce different scores for different distributions."""
        vals1 = {
            "social_engagement": 80.0,
            "sales_velocity": 60.0,
            "review_sentiment": 70.0,
            "trend_alignment": 90.0,
        }
        vals2 = {
            "social_engagement": 90.0,
            "sales_velocity": 70.0,
            "review_sentiment": 60.0,
            "trend_alignment": 80.0,
        }
        # Not equal because weights are not uniform (0.35, 0.30, 0.20, 0.15)
        assert compute_score(vals1) != compute_score(vals2)

    def test_same_distribution_same_score(self):
        """Identical inputs produce identical output."""
        vals = {
            "social_engagement": 80.0,
            "sales_velocity": 60.0,
            "review_sentiment": 70.0,
            "trend_alignment": 90.0,
        }
        assert compute_score(vals) == compute_score(vals)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Score bounds and rounding
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreBoundsAndRounding:
    def test_clamped_at_100(self):
        vals = {c["id"]: 100.0 for c in SCORING_COMPONENTS}
        assert compute_score(vals) <= SCORE_MAX

    def test_clamped_at_0(self):
        vals = {c["id"]: 0.0 for c in SCORING_COMPONENTS}
        assert compute_score(vals) >= SCORE_MIN

    def test_returns_integer(self):
        vals = {
            "social_engagement": 73.7,
            "sales_velocity": 81.3,
            "review_sentiment": 66.9,
            "trend_alignment": 92.1,
        }
        result = compute_score(vals)
        assert isinstance(result, int)

    def test_rounding_to_nearest(self):
        vals = {
            "social_engagement": 50.6,
            "sales_velocity": 50.6,
            "review_sentiment": 50.6,
            "trend_alignment": 50.6,
        }
        result = compute_score(vals)
        assert result == 51


# ══════════════════════════════════════════════════════════════════════════════
# 4. Error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_missing_component_raises(self):
        vals = {"social_engagement": 50.0, "sales_velocity": 50.0}
        with pytest.raises(ValueError, match="Missing required component"):
            compute_score(vals)

    def test_out_of_bounds_high_raises(self):
        vals = {c["id"]: 101.0 for c in SCORING_COMPONENTS}
        with pytest.raises(ValueError, match="out of bounds"):
            compute_score(vals)

    def test_out_of_bounds_low_raises(self):
        vals = {c["id"]: -1.0 for c in SCORING_COMPONENTS}
        with pytest.raises(ValueError, match="out of bounds"):
            compute_score(vals)

    def test_non_numeric_raises(self):
        vals = {c["id"]: 50.0 for c in SCORING_COMPONENTS}
        vals["social_engagement"] = "fifty"
        with pytest.raises(ValueError, match="must be numeric"):
            compute_score(vals)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Scoring record construction
# ══════════════════════════════════════════════════════════════════════════════


class TestScoringRecord:
    def test_record_has_required_fields(self):
        vals = {
            "social_engagement": 80.0,
            "sales_velocity": 70.0,
            "review_sentiment": 90.0,
            "trend_alignment": 60.0,
        }
        rec = build_scoring_record("test/product/1", vals, displayed_score=73)
        assert "product_id" in rec
        assert "recomputed_score" in rec
        assert "displayed_score" in rec
        assert "match" in rec
        assert "components" in rec
        assert "policy_version" in rec

    def test_record_match_when_equal(self):
        vals = {c["id"]: 80.0 for c in SCORING_COMPONENTS}
        score = compute_score(vals)
        rec = build_scoring_record("p1", vals, displayed_score=score)
        assert rec["match"] is True
        assert rec["recomputed_score"] == score

    def test_record_mismatch_when_different(self):
        vals = {c["id"]: 80.0 for c in SCORING_COMPONENTS}
        rec = build_scoring_record("p1", vals, displayed_score=99)
        assert rec["match"] is False

    def test_record_no_displayed(self):
        vals = {c["id"]: 80.0 for c in SCORING_COMPONENTS}
        rec = build_scoring_record("p1", vals)
        assert rec["displayed_score"] is None
        assert rec["match"] is True

    def test_record_policy_version(self):
        vals = {c["id"]: 50.0 for c in SCORING_COMPONENTS}
        rec = build_scoring_record("p1", vals)
        assert rec["policy_version"] == SCORING_POLICY_VERSION


# ══════════════════════════════════════════════════════════════════════════════
# 6. scoring.json schema validation
# ══════════════════════════════════════════════════════════════════════════════


class TestScoringJsonValidation:
    def test_week28_non_recomputable_validates(self, scoring_data):
        errors = validate_scoring_json(scoring_data)
        assert errors == [], f"Week 28 scoring.json validation errors: {errors}"

    def test_week28_recomputable_is_false(self, scoring_data):
        assert scoring_data.get("recomputable") is False

    def test_week28_has_version(self, scoring_data):
        assert "version" in scoring_data

    def test_week28_no_policy_block(self, scoring_data):
        assert scoring_data.get("policy") is None

    def test_week28_no_per_product(self, scoring_data):
        assert scoring_data.get("per_product") is None

    def test_valid_recomputable_json(self):
        scoring = {
            "version": SCORING_POLICY_VERSION,
            "schema": SCORING_SCHEMA,
            "recomputable": True,
            "policy": build_policy_block(),
            "per_product": [],
            "provenance": {"status": "recomputed"},
            "observed_statistics": {"total_scored_products": 0},
        }
        errors = validate_scoring_json(scoring)
        assert errors == []

    def test_recomputable_missing_policy(self):
        scoring = {
            "version": SCORING_POLICY_VERSION,
            "recomputable": True,
            "per_product": [],
            "provenance": {"status": "recomputed"},
        }
        errors = validate_scoring_json(scoring)
        assert any("policy block" in e for e in errors)

    def test_recomputable_missing_per_product(self):
        scoring = {
            "version": SCORING_POLICY_VERSION,
            "recomputable": True,
            "policy": build_policy_block(),
            "provenance": {"status": "recomputed"},
        }
        errors = validate_scoring_json(scoring)
        assert any("per_product" in e for e in errors)

    def test_recomputable_bad_provenance(self):
        scoring = {
            "version": SCORING_POLICY_VERSION,
            "recomputable": True,
            "policy": build_policy_block(),
            "per_product": [],
            "provenance": {"status": "historical_preserved"},
        }
        errors = validate_scoring_json(scoring)
        assert any("recomputed" in e for e in errors)

    def test_recomputable_with_mismatch_fails(self):
        scoring = {
            "version": SCORING_POLICY_VERSION,
            "recomputable": True,
            "policy": build_policy_block(),
            "per_product": [
                {
                    "product_id": "x",
                    "recomputed_score": 80,
                    "displayed_score": 80,
                    "match": False,
                }
            ],
            "provenance": {"status": "recomputed"},
        }
        errors = validate_scoring_json(scoring)
        assert any("recomputed" in e.lower() for e in errors)

    def test_non_recomputable_rejects_policy(self):
        scoring = {
            "version": "1.0.0",
            "recomputable": False,
            "policy": build_policy_block(),
            "missing_components": ["test"],
            "reason": "test",
        }
        errors = validate_scoring_json(scoring)
        assert any("policy block" in e for e in errors)

    def test_non_recomputable_rejects_per_product(self):
        scoring = {
            "version": "1.0.0",
            "recomputable": False,
            "per_product": [],
            "missing_components": ["test"],
            "reason": "test",
        }
        errors = validate_scoring_json(scoring)
        assert any("per_product" in e for e in errors)

    def test_missing_version_fails(self):
        scoring = {"recomputable": False}
        errors = validate_scoring_json(scoring)
        assert any("version" in e for e in errors)

    def test_missing_recomputable_fails(self):
        scoring = {"version": "1.0.0"}
        errors = validate_scoring_json(scoring)
        assert any("recomputable" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Score consistency against report data
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreConsistency:
    def test_non_recomputable_no_consistency_check(self, scoring_data, report_data):
        errors = validate_recomputed_scoring(scoring_data, report_data)
        assert errors == []

    def test_recomputable_consistency_check(self, report_data):
        vals = {c["id"]: 80.0 for c in SCORING_COMPONENTS}
        per_product = []
        products = report_data.get("products", {})
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = products.get(topic, {}).get(section, {})
                for panel_key, plist in panels.items():
                    for idx, p in enumerate(plist):
                        pid = f"{topic}/{section}/{panel_key}/{idx}"
                        score = p.get("score", 0)
                        per_product.append(
                            {
                                "product_id": pid,
                                "recomputed_score": compute_score(vals),
                                "displayed_score": score,
                                "match": compute_score(vals) == score,
                            }
                        )
        scoring = {
            "version": SCORING_POLICY_VERSION,
            "recomputable": True,
            "policy": build_policy_block(),
            "per_product": per_product,
            "provenance": {"status": "recomputed"},
        }
        # Most will mismatch since we used uniform 80 for all — but the
        # validate_recomputed_scoring function catches those mismatches.
        errors = validate_recomputed_scoring(scoring, report_data)
        # We expect some mismatches since we didn't use real signals
        # But no structural errors
        structural = [e for e in errors if "Score mismatch" not in e]
        assert structural == []


# ══════════════════════════════════════════════════════════════════════════════
# 8. Week 28 historical records
# ══════════════════════════════════════════════════════════════════════════════


class TestWeek28Historical:
    def test_week28_scores_preserved(self, scoring_data):
        stats = scoring_data.get("observed_statistics", {})
        assert stats.get("observed_min") is not None
        assert stats.get("observed_max") is not None
        assert stats.get("total_scored_products", 0) > 0

    def test_week28_no_weighted_components(self, scoring_data):
        assert scoring_data.get("components") is None
        assert scoring_data.get("weights") is None

    def test_week28_reason_documented(self, scoring_data):
        assert "reason" in scoring_data
        assert len(scoring_data["reason"]) > 0

    def test_week28_missing_components_documented(self, scoring_data):
        mc = scoring_data.get("missing_components", [])
        assert isinstance(mc, list)
        assert len(mc) >= 4

    def test_week28_validation_rules_checkable(self, scoring_data):
        rules = scoring_data.get("validation_rules", [])
        checkable = [r for r in rules if r.get("checkable")]
        assert len(checkable) >= 2

    def test_week28_not_recomputable(self, scoring_data):
        assert scoring_data.get("recomputable") is False

    def test_week28_no_reverse_engineering(self, scoring_data):
        """Scoring must not contain any reverse-engineered weight or methodology."""
        for key in ("methodology", "algorithm", "rubric"):
            assert key not in scoring_data, f"Must not invent '{key}'"
        assert scoring_data.get("components") is None
        assert scoring_data.get("weights") is None


# ══════════════════════════════════════════════════════════════════════════════
# 9. Backward compatibility with v1 scoring.json
# ══════════════════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    def test_v1_format_validates(self, scoring_data):
        """The existing v1 scoring.json must pass Phase 6 validation."""
        errors = validate_scoring_json(scoring_data)
        assert errors == []

    def test_v1_has_observed_statistics(self, scoring_data):
        stats = scoring_data.get("observed_statistics", {})
        assert "observed_min" in stats
        assert "observed_max" in stats

    def test_v1_has_known_constraints(self, scoring_data):
        kc = scoring_data.get("known_constraints", {})
        assert "min" in kc
        assert "max" in kc


# ══════════════════════════════════════════════════════════════════════════════
# 10. Policy block construction
# ══════════════════════════════════════════════════════════════════════════════


class TestPolicyBlock:
    def test_policy_block_structure(self):
        block = build_policy_block()
        assert block["version"] == SCORING_POLICY_VERSION
        assert block["schema"] == SCORING_SCHEMA
        assert len(block["components"]) == 4
        assert len(block["weights"]) == 4
        assert abs(block["total_weight"] - 1.0) < 1e-9
        assert block["score_bounds"] == {"min": 0, "max": 100}
        assert block["rounding"] == "nearest_integer"

    def test_policy_block_components_match(self):
        block = build_policy_block()
        for expected, actual in zip(SCORING_COMPONENTS, block["components"]):
            assert actual["id"] == expected["id"]
            assert actual["weight"] == expected["weight"]
            assert actual["bounds"] == expected["bounds"]


# ══════════════════════════════════════════════════════════════════════════════
# 11. Protected files unchanged
# ══════════════════════════════════════════════════════════════════════════════


class TestProtectedFiles:
    def test_week28_json_unchanged(self):
        p = ROOT / "data" / "week28.json"
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        assert h == "db31d10d682ace6f4ae43183816d2c31913b4da09c5030db1fedfaf6f1221ac8"

    def test_html_files_exist(self):
        for name in HTML_FILES:
            assert (ROOT / name).exists(), f"Missing: {name}"

    def test_week28_scoring_json_hash(self, scoring_data):
        """Week 28 scoring.json must not have changed (hash preserved)."""
        scoring_path = WEEKS_DIR / "scoring.json"
        h = hashlib.sha256(scoring_path.read_bytes()).hexdigest()
        assert h == "71f1b5b6da70d25b97a74287670c025286b1c4e837ed9ff62f722eaeaca6ee9a"
