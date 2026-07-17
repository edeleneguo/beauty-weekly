"""Canonical weekly dataset generation, loading, and validation.

Phase 4: generates an independent canonical dataset under
``data/weeks/<iso_week>/`` from the legacy ``data/week28.json``.  The
canonical dataset is the single source of truth for downstream consumers.

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
* Byte-for-byte compatibility with ``data/week28.json`` and the four
  production HTML files is preserved.
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
    WeeklyReport,
)

_ROOT = Path(__file__).resolve().parent.parent
WEEKS_DIR = _ROOT / "data" / "weeks"
LEGACY_PATH = _ROOT / "data" / "week28.json"
HTML_FILES = ("index.html", "index-cn.html", "fragrance.html", "fragrance-cn.html")

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

    return {
        "version": "1.0.0",
        "generated_from": "data/week28.json",
        "total_sources": len(seen_urls),
        "sources": sorted(seen_urls.values(), key=lambda s: s["id"]),
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

    # 3. Validate report.json against target schema
    try:
        WeeklyReport.model_validate(report, strict=False)
    except Exception as exc:
        errors.append(f"report.json fails target schema validation: {exc}")
        return errors

    # 4. Validate report.json against legacy data losslessly
    try:
        legacy = load_legacy_report(LEGACY_PATH)
        legacy_target, _warnings = to_target(legacy)
        legacy_dict = legacy_target.model_dump(mode="json", exclude_unset=True)
        if report != legacy_dict:
            errors.append("report.json differs from adapter-generated target model")
    except Exception as exc:
        errors.append(f"Legacy cross-validation failed: {exc}")

    # 5. Validate scoring.json
    if scoring.get("recomputable") is not False:
        errors.append("scoring.json must have recomputable=false for legacy data")
    if scoring.get("components") is not None:
        errors.append("scoring.json components must be null (no components available)")
    if scoring.get("weights") is not None:
        errors.append("scoring.json weights must be null (no weights available)")
    if "version" not in scoring:
        errors.append("scoring.json missing version")
    if "missing_components" not in scoring:
        errors.append("scoring.json missing missing_components list")
    if "validation_rules" not in scoring:
        errors.append("scoring.json missing validation_rules")

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


# ── Convenience ───────────────────────────────────────────────────────────────


def load_canonical_report(iso_week: str = "2026-W28") -> WeeklyReport:
    """Load and validate the canonical report for *iso_week*."""
    report_path = WEEKS_DIR / iso_week / "report.json"
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return WeeklyReport.model_validate(data, strict=False)
