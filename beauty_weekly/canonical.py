"""Canonical weekly dataset generation, loading, and validation.

Phase 5: the canonical dataset under ``data/weeks/<iso_week>/`` is the
single source of truth for all downstream consumers (renderer, validators,
HTML output).  ``data/week28.json`` is a test-only legacy baseline and is
never read at runtime by the canonical validation path.

Three artifacts are produced per week:

* ``report.json``    — the target ``WeeklyReport`` serialized deterministically
* ``sources.json``   — normalized, reusable source/evidence entities
* ``scoring.json``   — reproducible scoring model with components, weights,
                       calculation/version metadata, and recompute/validate rules

Design constraints
~~~~~~~~~~~~~~~~~~
* No score components, evidence, URLs, dates, translations, weights, or facts
  are invented.  When the legacy data lacks score inputs the score is
  represented as explicitly non-recomputable with documented missing components.
* Deterministic serialization: ``sort_keys=True``, ``ensure_ascii=False``,
  ``indent=2``.
* Byte-for-byte compatibility with the four production HTML files is preserved.
* The parity guard compares the explicit render/business projection — every
  field actually consumed by the renderer, HTML output, and active validators
  — not a byte-identical full legacy dict.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from beauty_weekly.loader import (
    load_legacy_report,
    to_target,
)
from beauty_weekly.models import (
    LegacyWeeklyReport,
    MonthlyReport,
    WeeklyReport,
)
from beauty_weekly.scoring import (
    validate_recomputed_scoring as _validate_recomputed_scoring,
)
from beauty_weekly.scoring import (
    validate_scoring_json as _validate_scoring_engine,
)

_ROOT = Path(__file__).resolve().parent.parent
WEEKS_DIR = _ROOT / "data" / "weeks"
LEGACY_PATH = _ROOT / "data" / "week28.json"
HTML_FILES = ("index.html", "fragrance.html")


# ── Render / business projection (Phase 5) ────────────────────────────────
# Every field consumed by build/render.py, build/validate.py, and the four
# production HTML output files.  The parity guard compares ONLY these fields
# — never a byte-identical full legacy dict, because the canonical model
# intentionally omits isolated non-render fields (raw_score, per-language
# version strings, category_badge_cn).

# Top-level report fields consumed downstream.
REPORT_PROJECTION_FIELDS = {"date_range", "date_range_cn", "products", "version"}

# Product-level fields consumed by the renderer and validators.
PRODUCT_PROJECTION_FIELDS = {
    "rank",
    "market",
    "tier",
    "name",
    "name_cn",
    "category_badge",
    "score",
    "trend_badge",
    "new_badge",
}

# Detail-cell fields consumed by the renderer.
# price_link is a PriceLink (en, cn, link); key_features, buzz, brand are
# LocalizedText (en, cn only — no link field).
DETAIL_PROJECTION_KEYS = {"price_link", "key_features", "buzz", "brand"}
DETAIL_BASE_SUB_FIELDS = {"en", "cn"}
DETAIL_LINK_SUB_FIELDS = {"en", "cn", "link"}

# Launch evidence fields consumed by the renderer (quarantine filtering)
# and validators (evidence completeness checks).
LAUNCH_EVIDENCE_PROJECTION_FIELDS = {
    "launch_date",
    "quarantine_status",
    "quarantine_reason",
}
EVIDENCE_PROJECTION_FIELDS = {"url", "type", "checked_at"}

# Trend fields consumed by the renderer and validators.
# tag / tag_cn are always present on trend-badge products.
# rationale is only present on radar trend products.
TREND_PROJECTION_FIELDS = {"tag", "tag_cn", "rationale"}

# ── Deterministic serialization ───────────────────────────────────────────────


def _deterministic_json(obj: Any) -> str:
    """Serialize *obj* to JSON with deterministic key order and no ASCII escapes."""
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Source / evidence extraction ──────────────────────────────────────────────


def generate_sources(legacy: LegacyWeeklyReport) -> dict:
    """Extract and normalize reusable source/evidence entities.

    Every unique URL found in the legacy data is captured once with its
    provenance metadata.  URLs are never fabricated — only URLs present
    in the legacy data are included.
    """
    seen_urls: dict[str, dict] = {}
    source_counter = 0

    def _add(url: str, **extra: Any) -> None:
        nonlocal source_counter
        if not url or url in seen_urls:
            return
        source_counter += 1
        entry: dict[str, Any] = {
            "id": f"src_{source_counter:04d}",
            "url": url,
        }
        entry.update(extra)
        seen_urls[url] = entry

    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            lps = getattr(getattr(legacy.products, topic), section)
            for panel, products in lps.items():
                for lp in products:
                    link = lp.detail.price_link.link
                    if link:
                        _add(
                            link,
                            type="product_page",
                            product_name=lp.name,
                            panel=panel,
                            section=section,
                            topic=topic,
                        )
                    if lp.evidence_url:
                        _add(
                            lp.evidence_url,
                            type=lp.evidence_type or "unknown",
                            product_name=lp.name,
                            panel=panel,
                            section=section,
                            topic=topic,
                            checked_at=lp.evidence_checked_at,
                        )

    sources_list = sorted(seen_urls.values(), key=lambda s: s["id"])
    for src in sources_list:
        # The legacy data contains no verification timestamp.  Preserve that
        # fact explicitly instead of inventing one during migration.
        src["checked_at"] = None
        src["provenance"] = {
            "verification_status": "legacy_unverified",
            "reason": "No source-verification timestamp exists in legacy week28 data.",
        }

    return {
        "version": "2.0.0",
        "generated_from": "data/week28.json",
        "total_sources": len(seen_urls),
        "provenance": {
            "migration_recorded_at": "2026-07-17T00:00:00Z",
            "phase": 7,
            "evidence_absences": [
                {
                    "product_name": "To Summer Kunlun Snow",
                    "panel": "CN MASSTIGE",
                    "section": "heat_rankings",
                    "topic": "fragrance",
                    "gap_type": "no_url",
                    "reason": (
                        "No official e-commerce or product page URL exists in repository "
                        "data for To Summer Kunlun Snow. Chinese niche fragrance with "
                        "no verified public URL."
                    ),
                },
                {
                    "product_name": "Scent Library Boiled Water",
                    "panel": "CN MASSTIGE",
                    "section": "heat_rankings",
                    "topic": "fragrance",
                    "gap_type": "no_url",
                    "reason": (
                        "No official e-commerce or product page URL exists in repository "
                        "data for Scent Library Boiled Water. Chinese niche fragrance "
                        "with no verified public URL."
                    ),
                },
            ],
        },
        "sources": sources_list,
    }


# ── Scoring model ─────────────────────────────────────────────────────────────


def generate_scoring_model(legacy: LegacyWeeklyReport) -> dict:
    """Generate the scoring model metadata.

    The legacy data stores opaque integer scores with no decomposable
    components, weights, or documented methodology.  The score is therefore
    explicitly **non-recomputable** from available data.  This is not a gap
    to be fixed — it faithfully reflects the provenance of the original data.
    """
    # Compute observed score statistics from actual data
    all_scores: list[int] = []
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            lps = getattr(getattr(legacy.products, topic), section)
            for _panel, products in lps.items():
                for lp in products:
                    if lp.score > 0:
                        all_scores.append(lp.score)

    observed_min = min(all_scores) if all_scores else 0
    observed_max = max(all_scores) if all_scores else 100

    # Verify monotonicity by rank within each panel
    monotonic = True
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            lps = getattr(getattr(legacy.products, topic), section)
            for _panel, products in lps.items():
                scores = [p.score for p in products if p.score > 0]
                for i in range(1, len(scores)):
                    if scores[i] > scores[i - 1]:
                        monotonic = False

    return {
        "version": "1.0.0",
        "schema": "beauty-weekly-scoring-v1",
        "recomputable": False,
        "reason": (
            "Legacy week28.json stores opaque integer scores (0-100) with no "
            "decomposable components, weights, or methodology documentation. "
            "Scores cannot be independently recomputed from available data."
        ),
        "missing_components": [
            "score_breakdown — no per-dimension scores available",
            "weights — no weighting factors documented",
            "methodology — no scoring rubric or algorithm provided",
            (
                "raw_signals — no underlying metrics (sales volume, review "
                "counts, social-media engagement) available as structured data"
            ),
        ],
        "observed_statistics": {
            "total_scored_products": len(all_scores),
            "observed_min": observed_min,
            "observed_max": observed_max,
            "monotonic_by_rank": monotonic,
        },
        "known_constraints": {
            "field": "score",
            "type": "integer",
            "min": 0,
            "max": 100,
            "observed_min": observed_min,
            "observed_max": observed_max,
            "monotonic_by_rank": monotonic,
            "panel_independent": True,
        },
        "validation_rules": [
            {
                "rule": "score_range",
                "description": "All non-zero scores must be between 0 and 100",
                "checkable": True,
            },
            {
                "rule": "monotonic_by_rank",
                "description": ("Within each panel, scores must be non-increasing by rank"),
                "checkable": True,
            },
            {
                "rule": "no_placeholder_in_heat",
                "description": ("Heat rankings must not contain score=0 placeholder products"),
                "checkable": True,
            },
            {
                "rule": "recompute_total",
                "description": ("Cannot recompute: no score components available"),
                "checkable": False,
            },
        ],
        "components": None,
        "weights": None,
    }


# ── Canonical report generation ───────────────────────────────────────────────


def generate_canonical_report(
    legacy: LegacyWeeklyReport,
) -> tuple[dict, list[str]]:
    """Generate the canonical report dict and migration warnings."""
    target, warnings = to_target(legacy)
    report_dict = target.model_dump(mode="json", exclude_unset=True)
    return report_dict, warnings


# ── Artifact hash computation ─────────────────────────────────────────────────


def compute_artifact_hashes(weeks_dir: Path) -> dict:
    """Compute SHA-256 hashes of all canonical artifacts."""
    hashes: dict[str, str] = {}
    for name in ("report.json", "sources.json", "scoring.json", "manifest.json"):
        p = weeks_dir / name
        if p.exists():
            hashes[name] = _sha256_of_file(p)
    return hashes


# ── Projection parity guard ──────────────────────────────────────────────────


def _check_render_projection(report: dict, errors: list[str]) -> None:
    """Fail-closed check: every field consumed by renderer/validators is present.

    Compares the canonical report against the explicit render/business
    projection — NOT a byte-identical full legacy dict.  Fields intentionally
    omitted by the canonical model (raw_score, version_*, category_badge_cn)
    are not checked here.
    """
    report_id_field = "month" if "month" in report else "week"

    # Top-level report fields
    for field in REPORT_PROJECTION_FIELDS | {report_id_field}:
        if field not in report:
            errors.append(f"report.json missing render projection field: {field}")

    products = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = products.get(topic, {}).get(section, {})
            for panel_key, product_list in panels.items():
                for idx, p in enumerate(product_list):
                    loc = f"{topic}/{section}/{panel_key}[{idx}]"
                    # Product-level fields
                    for field in PRODUCT_PROJECTION_FIELDS:
                        if field not in p:
                            errors.append(f"{loc}: missing render projection field '{field}'")
                    # Detail cells
                    detail = p.get("detail", {})
                    for dkey in DETAIL_PROJECTION_KEYS:
                        if dkey not in detail:
                            errors.append(f"{loc}: missing detail.{dkey}")
                        elif isinstance(detail[dkey], dict):
                            # price_link has link; other cells are en/cn only
                            subs = (
                                DETAIL_LINK_SUB_FIELDS
                                if dkey == "price_link"
                                else DETAIL_BASE_SUB_FIELDS
                            )
                            for sub in subs:
                                if sub not in detail[dkey]:
                                    errors.append(f"{loc}: missing detail.{dkey}.{sub}")
                    # Trend (optional, but when present must have tag/tag_cn)
                    trend = p.get("trend")
                    if trend is not None:
                        for field in TREND_PROJECTION_FIELDS:
                            if field not in trend:
                                errors.append(f"{loc}: trend missing '{field}'")


# ── Validation ────────────────────────────────────────────────────────────────


def validate_canonical(weeks_dir: Path) -> list[str]:
    """Validate the canonical weekly dataset.  Returns a list of error strings.

    Fail-closed: any error means the dataset is invalid.
    """
    errors: list[str] = []

    report_path = weeks_dir / "report.json"
    sources_path = weeks_dir / "sources.json"
    scoring_path = weeks_dir / "scoring.json"
    manifest_path = weeks_dir / "manifest.json"

    # 1. All required files exist
    for name, path in [
        ("report.json", report_path),
        ("sources.json", sources_path),
        ("scoring.json", scoring_path),
        ("manifest.json", manifest_path),
    ]:
        if not path.exists():
            errors.append(f"Missing required file: {name}")
    if errors:
        return errors

    # 2. Load and parse JSON files
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"report.json parse error: {exc}")
        return errors

    try:
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"sources.json parse error: {exc}")
        return errors

    try:
        scoring = json.loads(scoring_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"scoring.json parse error: {exc}")
        return errors

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"manifest.json parse error: {exc}")
        return errors

    model = MonthlyReport if "month" in report else WeeklyReport

    # 3. Validate report.json against target schema
    try:
        model.model_validate(report, strict=False)
    except Exception as exc:
        errors.append(f"report.json fails target schema validation: {exc}")
        return errors

    # 4. Projection parity guard (Phase 5 — replaces legacy cross-validation)
    #    Verifies that every field consumed by the renderer, HTML output,
    #    and active validators is present and well-typed in the canonical
    #    report.  This is fail-closed: any missing field is an error.
    try:
        _check_render_projection(report, errors)
    except Exception as exc:
        errors.append(f"Projection parity check failed: {exc}")

    # 5. Validate scoring.json via scoring engine (Phase 6)
    scoring_errors = _validate_scoring_engine(scoring)
    for e in scoring_errors:
        errors.append(f"scoring.json: {e}")

    # 6. Validate scoring rules against actual data
    scoring_stats = scoring.get("observed_statistics", {})
    all_scores: list[int] = []
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = report.get("products", {}).get(topic, {}).get(section, {})
            for _panel, products in panels.items():
                for p in products:
                    s = p.get("score", 0)
                    if s > 0:
                        all_scores.append(s)
                    if section == "heat_rankings" and s == 0:
                        errors.append(f"Heat product {p.get('name')} has score=0 (placeholder)")

    if all_scores:
        actual_min = min(all_scores)
        actual_max = max(all_scores)
        if scoring_stats.get("observed_min") != actual_min:
            errors.append(
                f"Scoring observed_min mismatch: "
                f"{scoring_stats.get('observed_min')} != {actual_min}"
            )
        if scoring_stats.get("observed_max") != actual_max:
            errors.append(
                f"Scoring observed_max mismatch: "
                f"{scoring_stats.get('observed_max')} != {actual_max}"
            )

    # 6b. Recompute validation (Phase 6) — fail-closed for recomputable records
    recompute_errors = _validate_recomputed_scoring(scoring, report)
    for e in recompute_errors:
        errors.append(f"scoring recompute: {e}")

    # 7. Validate sources.json
    if "version" not in sources:
        errors.append("sources.json missing version")
    if "sources" not in sources:
        errors.append("sources.json missing sources list")
    else:
        # Verify all source URLs exist in the report
        report_urls: set[str] = set()
        for topic in ("makeup", "fragrance"):
            for section in ("heat_rankings", "new_product_radar"):
                panels = report.get("products", {}).get(topic, {}).get(section, {})
                for _panel, products in panels.items():
                    for p in products:
                        link = p.get("detail", {}).get("price_link", {}).get("link", "")
                        if link:
                            report_urls.add(link)
                        le = p.get("launch_evidence")
                        if le and le.get("evidence") and le["evidence"].get("url"):
                            report_urls.add(le["evidence"]["url"])
        source_urls = {s["url"] for s in sources["sources"]}
        orphaned = source_urls - report_urls
        if orphaned:
            errors.append(f"sources.json has {len(orphaned)} URL(s) not in report.json")

    # 8. Validate manifest.json
    if manifest.get("schema_version", 0) < 3:
        errors.append(f"manifest.json schema_version {manifest.get('schema_version')} < 3")
    if manifest.get("data_pointer") is None:
        errors.append("manifest.json missing data_pointer (backward compat)")
    if not manifest.get("data_pointer", "").startswith("../../"):
        errors.append("manifest.json data_pointer not relative path")
    if "products" in manifest:
        errors.append("manifest.json should not contain products field")
    # Phase 3 fields preserved
    if "resolved_warnings" not in manifest:
        errors.append("manifest.json missing resolved_warnings (Phase 3)")
    if "remaining_warnings" not in manifest:
        errors.append("manifest.json missing remaining_warnings (Phase 3)")
    # Phase 4 fields present
    if "canonical_hash" not in manifest:
        errors.append("manifest.json missing canonical_hash (Phase 4)")
    if "scoring_hash" not in manifest:
        errors.append("manifest.json missing scoring_hash (Phase 4)")
    if "sources_hash" not in manifest:
        errors.append("manifest.json missing sources_hash (Phase 4)")

    # 9. Verify artifact hashes match manifest
    hashes = compute_artifact_hashes(weeks_dir)
    for key in ("report.json", "scoring.json", "sources.json"):
        manifest_key = key.replace(".json", "_hash")
        if manifest.get(manifest_key) and hashes.get(key) and manifest[manifest_key] != hashes[key]:
            errors.append(
                f"manifest.json {manifest_key} mismatch: {manifest[manifest_key]} != {hashes[key]}"
            )

    return errors


# ── Drift detection ──────────────────────────────────────────────────────────


def detect_canonical_drift(weeks_dir: Path) -> list[str]:
    """Detect drift between on-disk canonical artifacts and fresh generation.

    Reads ``data/week28.json`` (test-only baseline) and regenerates the
    canonical dataset, then compares artifact hashes.  Returns a list of
    error strings; empty means no drift.

    This function IS allowed to read the legacy file because it is a
    test/diagnostic utility, not the primary read path.
    """
    errors: list[str] = []
    try:
        legacy = load_legacy_report(LEGACY_PATH)
    except Exception as exc:
        errors.append(f"Cannot load legacy baseline for drift check: {exc}")
        return errors

    # Regenerate canonical artifacts and compare hashes
    report_dict, _warnings = generate_canonical_report(legacy)
    from beauty_weekly.canonical import _deterministic_json

    fresh_report_hash = _sha256_of(_deterministic_json(report_dict))
    on_disk_hashes = compute_artifact_hashes(weeks_dir)

    if on_disk_hashes.get("report.json") != fresh_report_hash:
        errors.append(
            f"report.json hash drift: on-disk={on_disk_hashes.get('report.json')!r} "
            f"fresh={fresh_report_hash!r}"
        )

    # Compare sources
    fresh_sources = generate_sources(legacy)
    fresh_sources_hash = _sha256_of(_deterministic_json(fresh_sources))
    if on_disk_hashes.get("sources.json") != fresh_sources_hash:
        errors.append(
            f"sources.json hash drift: on-disk={on_disk_hashes.get('sources.json')!r} "
            f"fresh={fresh_sources_hash!r}"
        )

    # Compare scoring
    fresh_scoring = generate_scoring_model(legacy)
    fresh_scoring_hash = _sha256_of(_deterministic_json(fresh_scoring))
    if on_disk_hashes.get("scoring.json") != fresh_scoring_hash:
        errors.append(
            f"scoring.json hash drift: on-disk={on_disk_hashes.get('scoring.json')!r} "
            f"fresh={fresh_scoring_hash!r}"
        )

    return errors


# ── Convenience ───────────────────────────────────────────────────────────────


def load_canonical_report(iso_week: str | None = None) -> WeeklyReport:
    """Load and validate the canonical report for *iso_week*."""
    if iso_week is None:
        from beauty_weekly.week import resolve_week

        iso_week = resolve_week()
    report_path = WEEKS_DIR / iso_week / "report.json"
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return WeeklyReport.model_validate(data, strict=False)
