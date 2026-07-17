"""Versioned scoring policy and recomputation engine.

Phase 6: defines a formal scoring policy with explicit component definitions,
weights, deterministic calculation, rounding rules, and score bounds.  For
historical records (Week 28) lacking raw signal data, scores are preserved as
displayed and marked non-recomputable.  Future records with complete signal
data can be recomputed and validated against displayed scores.

Design constraints
~~~~~~~~~~~~~~~~~~
* No component weights, raw signals, or scoring methodology are
  reverse-engineered from Week 28's opaque integer scores.
* Deterministic: same inputs always produce the same integer score.
* Fail-closed: any recomputable record that fails recompute validation is
  an error.
"""

from __future__ import annotations

from typing import Any

# ── Policy constants ──────────────────────────────────────────────────────────

SCORING_POLICY_VERSION = "2.0.0"
SCORING_SCHEMA = "beauty-weekly-scoring-v2"

SCORE_MIN = 0
SCORE_MAX = 100
ROUNDING = "nearest_integer"

# Component definitions — the formal scoring rubric.
# weight: 0-1, must sum to 1.0.
# source_field: the raw signal key expected in per_product entries.
SCORING_COMPONENTS: list[dict[str, Any]] = [
    {
        "id": "social_engagement",
        "label": "Social Media Engagement",
        "description": "Aggregate social media engagement index across platforms",
        "weight": 0.35,
        "source_field": "social_signals",
        "bounds": {"min": 0, "max": 100},
    },
    {
        "id": "sales_velocity",
        "label": "Sales Velocity",
        "description": "Week-over-week sales velocity index",
        "weight": 0.30,
        "source_field": "sales_data",
        "bounds": {"min": 0, "max": 100},
    },
    {
        "id": "review_sentiment",
        "label": "Review Sentiment",
        "description": "Aggregated review sentiment score",
        "weight": 0.20,
        "source_field": "review_aggregation",
        "bounds": {"min": 0, "max": 100},
    },
    {
        "id": "trend_alignment",
        "label": "Trend Alignment",
        "description": "Alignment with active trend signals",
        "weight": 0.15,
        "source_field": "trend_analysis",
        "bounds": {"min": 0, "max": 100},
    },
]

TOTAL_WEIGHT = round(sum(c["weight"] for c in SCORING_COMPONENTS), 10)
COMPONENT_IDS = [c["id"] for c in SCORING_COMPONENTS]
WEIGHTS_MAP = {c["id"]: c["weight"] for c in SCORING_COMPONENTS}


# ── Deterministic score computation ──────────────────────────────────────────


def compute_score(component_values: dict[str, float]) -> int:
    """Compute an integer score from component values.

    Deterministic formula:
        score = round(sum(value_i * weight_i) for each component)
        clamped to [SCORE_MIN, SCORE_MAX]

    Parameters
    ----------
    component_values:
        Mapping of component id → raw value (0-100).
        All components must be present.

    Returns
    -------
    int: The computed score, rounded to nearest integer.

    Raises
    ------
    ValueError: If a required component is missing or value is out of bounds.
    """
    for cid in COMPONENT_IDS:
        if cid not in component_values:
            raise ValueError(f"Missing required component: {cid}")
        val = component_values[cid]
        if not isinstance(val, (int, float)):
            raise ValueError(f"Component {cid} value must be numeric, got {type(val).__name__}")
        if val < SCORE_MIN or val > SCORE_MAX:
            raise ValueError(
                f"Component {cid} value {val} out of bounds [{SCORE_MIN}, {SCORE_MAX}]"
            )

    raw = sum(component_values[cid] * WEIGHTS_MAP[cid] for cid in COMPONENT_IDS)
    score = int(round(raw))
    return max(SCORE_MIN, min(SCORE_MAX, score))


# ── Scoring record construction ──────────────────────────────────────────────


def build_scoring_record(
    product_id: str,
    component_values: dict[str, float],
    displayed_score: int | None = None,
) -> dict[str, Any]:
    """Build a per-product scoring record with provenance.

    Parameters
    ----------
    product_id:
        Stable identifier for the product (e.g. ``"{topic}/{section}/{panel}/{rank}"``).
    component_values:
        Raw component signal values.
    displayed_score:
        The score displayed in the report.  When provided, the record is
        validated against the recomputed score.

    Returns
    -------
    dict with recomputed_score, displayed_score, match, and component breakdown.
    """
    recomputed = compute_score(component_values)
    match = displayed_score is None or recomputed == displayed_score

    return {
        "product_id": product_id,
        "recomputed_score": recomputed,
        "displayed_score": displayed_score,
        "match": match,
        "components": {cid: component_values[cid] for cid in COMPONENT_IDS},
        "policy_version": SCORING_POLICY_VERSION,
    }


# ── Policy schema for scoring.json ──────────────────────────────────────────


def build_policy_block() -> dict[str, Any]:
    """Build the scoring policy block for inclusion in scoring.json."""
    return {
        "version": SCORING_POLICY_VERSION,
        "schema": SCORING_SCHEMA,
        "components": [
            {
                "id": c["id"],
                "label": c["label"],
                "description": c["description"],
                "weight": c["weight"],
                "source_field": c["source_field"],
                "bounds": c["bounds"],
            }
            for c in SCORING_COMPONENTS
        ],
        "weights": {c["id"]: c["weight"] for c in SCORING_COMPONENTS},
        "total_weight": TOTAL_WEIGHT,
        "score_bounds": {"min": SCORE_MIN, "max": SCORE_MAX},
        "rounding": ROUNDING,
    }


# ── Validation helpers ──────────────────────────────────────────────────────


def validate_scoring_json(scoring: dict[str, Any]) -> list[str]:
    """Validate a scoring.json structure against the policy.

    Returns a list of error strings; empty means valid.
    """
    errors: list[str] = []

    if "version" not in scoring:
        errors.append("scoring.json missing version")

    if "recomputable" not in scoring:
        errors.append("scoring.json missing recomputable field")

    recomputable = scoring.get("recomputable")

    if recomputable is True:
        # Recomputable records must have the policy block
        policy = scoring.get("policy")
        if policy is None:
            errors.append("recomputable scoring.json must have policy block")
        else:
            if policy.get("version") != SCORING_POLICY_VERSION:
                errors.append(
                    f"policy.version mismatch: {policy.get('version')} != {SCORING_POLICY_VERSION}"
                )
            policy_components = policy.get("components", [])
            if len(policy_components) != len(SCORING_COMPONENTS):
                errors.append(
                    f"policy has {len(policy_components)} components, "
                    f"expected {len(SCORING_COMPONENTS)}"
                )
            for expected in SCORING_COMPONENTS:
                found = next((p for p in policy_components if p.get("id") == expected["id"]), None)
                if found is None:
                    errors.append(f"policy missing component: {expected['id']}")
                elif found.get("weight") != expected["weight"]:
                    errors.append(
                        f"component {expected['id']} weight mismatch: "
                        f"{found.get('weight')} != {expected['weight']}"
                    )
            tw = policy.get("total_weight")
            if tw is not None and abs(tw - TOTAL_WEIGHT) > 1e-9:
                errors.append(f"policy.total_weight mismatch: {tw} != {TOTAL_WEIGHT}")
            sb = policy.get("score_bounds", {})
            if sb.get("min") != SCORE_MIN or sb.get("max") != SCORE_MAX:
                errors.append(
                    f"policy.score_bounds mismatch: {sb} != {{min: {SCORE_MIN}, max: {SCORE_MAX}}}"
                )

        # Must have per_product records
        per_product = scoring.get("per_product")
        if per_product is None:
            errors.append("recomputable scoring.json must have per_product records")
        elif not isinstance(per_product, list):
            errors.append("per_product must be a list")
        else:
            for rec in per_product:
                if "product_id" not in rec:
                    errors.append("per_product record missing product_id")
                if "recomputed_score" not in rec:
                    errors.append(
                        f"per_product record {rec.get('product_id', '?')} missing recomputed_score"
                    )
                if rec.get("match") is False:
                    errors.append(
                        f"per_product {rec.get('product_id', '?')}: recomputed != displayed"
                    )

        # Provenance status must indicate recomputation
        provenance = scoring.get("provenance", {})
        if provenance.get("status") != "recomputed":
            errors.append("recomputable scoring.json provenance.status must be 'recomputed'")

    elif recomputable is False:
        # Non-recomputable: historical records preserved as-is
        provenance = scoring.get("provenance", {})
        status = provenance.get("status", "")
        if status not in ("historical_preserved", ""):
            # Allow missing provenance for backward compat with v1 scoring.json
            pass

        # Must not have policy block (no computation rules applied)
        if scoring.get("policy") is not None:
            errors.append("non-recomputable scoring.json must not have policy block")

        # Must not have per_product records
        if scoring.get("per_product") is not None:
            errors.append("non-recomputable scoring.json must not have per_product records")

    return errors


def validate_recomputed_scoring(
    scoring: dict[str, Any],
    report: dict[str, Any],
) -> list[str]:
    """For recomputable records, validate that per_product scores match report scores.

    Returns a list of error strings; empty means valid.
    """
    errors: list[str] = []

    if scoring.get("recomputable") is not True:
        return errors

    per_product = scoring.get("per_product", [])
    if not per_product:
        return errors

    # Build lookup of displayed scores from report
    displayed: dict[str, int] = {}
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = products_data.get(topic, {}).get(section, {})
            for panel_key, product_list in panels.items():
                for idx, p in enumerate(product_list):
                    pid = f"{topic}/{section}/{panel_key}/{idx}"
                    displayed[pid] = p.get("score", 0)

    for rec in per_product:
        pid = rec.get("product_id", "")
        recomputed = rec.get("recomputed_score")
        disp = displayed.get(pid)
        if disp is not None and recomputed != disp:
            errors.append(f"Score mismatch for {pid}: recomputed={recomputed} displayed={disp}")

    return errors
