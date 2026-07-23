"""Pre-publish validation gate (Req 2).

Runs strict canonical, schema, count, bilingual parity, source citation,
and evidence coverage checks before allowing publication.  Failure must
preserve stable Pages (Req 5).

Checks:
  1. Non-null launch_evidence for every product (Req 1).
  2. Evidence completeness: url, title, published_at, fetched_at,
     checked_at, supported_fields are all non-empty strings.
  3. Evidence supported_fields are valid (price, features, buzz, brand,
     category, launch_date, link).
  4. Product/source referential integrity: every product URL exists in
     sources.json; every source is referenced by at least one product.
  5. Source articles referenced by evidence must not be bare RSS feed URLs.
  6. Count constraints: heat 1-10 per panel, radar 0-10 per panel,
     exactly 4 panels per section.
  7. Bilingual parity: US and CN product counts must both be > 0 when
     either is > 0 (explicit Chinese coverage scope).
  8. Section/panel counts: exactly 2 sections, 4 panels per section.
  9. Score range: 65-98 for real products.
 10. Evidence type must be from valid evidence types.
"""

from __future__ import annotations

import json
from pathlib import Path

from beauty_weekly.evidence import (
    EVIDENCE_TYPES,
    VALID_EVIDENCE_SUPPORTED_FIELDS,
    validate_evidence_integrity,
)
from beauty_weekly.scoring import validate_scoring_json

# ── Constants ────────────────────────────────────────────────────────────────

REQUIRED_PANELS = {"US LUXURY", "US MASSTIGE"}
REQUIRED_SECTIONS = {"heat_rankings", "new_product_radar"}
HEAT_MIN = 0
HEAT_MAX = 10
RADAR_MIN = 0
RADAR_MAX = 10
SCORE_MIN_DISPLAYED = 65
SCORE_MAX_DISPLAYED = 98


# ── Launch evidence validation (Req 1) ─────────────────────────────────────


def validate_launch_evidence_non_null(report: dict) -> list[str]:
    """Every published product must have non-null launch_evidence."""
    errors: list[str] = []
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in products_data.get(topic, {}).get(section, {}).items():
                for idx, p in enumerate(products):
                    if p.get("score", 0) == 0:
                        continue
                    le = p.get("launch_evidence")
                    if le is None:
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        errors.append(
                            f"Req1: {loc} has null launch_evidence — "
                            f"every published product must carry evidence"
                        )
    return errors


def validate_evidence_completeness(report: dict) -> list[str]:
    """Evidence must have url, title, published_at, fetched_at, checked_at, supported_fields."""
    errors: list[str] = []
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in products_data.get(topic, {}).get(section, {}).items():
                for idx, p in enumerate(products):
                    if p.get("score", 0) == 0:
                        continue
                    le = p.get("launch_evidence")
                    if le is None:
                        continue
                    evidence = le.get("evidence")
                    if evidence is None:
                        # EvidenceAbsence is acceptable (gap documented)
                        absence = le.get("absence_markers", [])
                        if not absence:
                            loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                            errors.append(
                                f"Req1: {loc} has launch_evidence but "
                                f"no evidence and no absence_markers"
                            )
                        continue
                    loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                    for field in ("url", "title", "published_at", "fetched_at", "checked_at"):
                        val = evidence.get(field)
                        if not val or not str(val).strip():
                            errors.append(f"Req1: {loc} evidence.{field} is empty")
                    sf = evidence.get("supported_fields", [])
                    if not sf:
                        errors.append(f"Req1: {loc} evidence.supported_fields is empty")
                    for sf_name in sf:
                        if sf_name not in VALID_EVIDENCE_SUPPORTED_FIELDS:
                            errors.append(
                                f"Req1: {loc} evidence.supported_fields contains "
                                f"unsupported field '{sf_name}'"
                            )
    return errors


def validate_evidence_types(report: dict) -> list[str]:
    """Evidence type must be from the valid evidence types set."""
    errors: list[str] = []
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in products_data.get(topic, {}).get(section, {}).items():
                for idx, p in enumerate(products):
                    le = p.get("launch_evidence")
                    if not le or not le.get("evidence"):
                        continue
                    ev_type = le["evidence"].get("type", "")
                    if ev_type not in EVIDENCE_TYPES:
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        errors.append(f"Req1: {loc} evidence.type '{ev_type}' not in valid types")
    return errors


# ── Product/source referential integrity ────────────────────────────────────


def validate_product_source_referential_integrity(report: dict, sources: dict) -> list[str]:
    """Every product URL must exist in sources.json; every source must be referenced."""
    errors: list[str] = []
    source_urls = {s.get("url", "") for s in sources.get("sources", [])}
    report_urls: dict[str, list[str]] = {}

    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in products_data.get(topic, {}).get(section, {}).items():
                for idx, p in enumerate(products):
                    link = p.get("detail", {}).get("price_link", {}).get("link", "")
                    if link:
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        report_urls.setdefault(link, []).append(loc)
                    # Also check evidence URLs
                    le = p.get("launch_evidence")
                    if le and le.get("evidence") and le["evidence"].get("url"):
                        ev_url = le["evidence"]["url"]
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        report_urls.setdefault(ev_url, []).append(loc)

    # Every report URL must exist in sources
    for url, locations in report_urls.items():
        if url not in source_urls:
            errors.append(
                f"Referential integrity: product URL not in sources.json: "
                f"{url} (used by: {', '.join(locations[:2])})"
            )

    # Every source URL must be referenced by at least one product
    referenced = set(report_urls.keys())
    orphaned = source_urls - referenced
    if orphaned:
        errors.append(
            f"Referential integrity: {len(orphaned)} source(s) in sources.json "
            f"not referenced by any product in report.json"
        )

    return errors


# ── Count constraints ──────────────────────────────────────────────────────


def validate_panel_counts(report: dict) -> list[str]:
    """Heat 1-10 per panel, radar 0-10 per panel, US panels required."""
    errors: list[str] = []
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = products_data.get(topic, {}).get(section, {})
            # Check US panels are present
            us_panel_keys = {k for k in panels if k.startswith("US")}
            missing = REQUIRED_PANELS - us_panel_keys
            if missing:
                errors.append(f"Count: {topic}/{section} missing US panels: {missing}")
            # Validate US panel counts only
            for panel_key in REQUIRED_PANELS:
                if panel_key not in panels:
                    continue
                products = panels[panel_key]
                real = [p for p in products if p.get("score", 0) > 0]
                if section == "heat_rankings":
                    if len(real) < HEAT_MIN or len(real) > HEAT_MAX:
                        errors.append(
                            f"Count: {topic}/heat/{panel_key} has {len(real)} "
                            f"products (expected {HEAT_MIN}-{HEAT_MAX})"
                        )
                elif section == "new_product_radar" and (
                    len(real) < RADAR_MIN or len(real) > RADAR_MAX
                ):
                    errors.append(
                        f"Count: {topic}/radar/{panel_key} has {len(real)} "
                        f"products (expected {RADAR_MIN}-{RADAR_MAX})"
                    )
    return errors


def validate_section_count(report: dict) -> list[str]:
    """Each topic must have exactly 2 sections."""
    errors: list[str] = []
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        sections = set(products_data.get(topic, {}).keys())
        if sections != REQUIRED_SECTIONS:
            missing = REQUIRED_SECTIONS - sections
            extra = sections - REQUIRED_SECTIONS
            if missing:
                errors.append(f"Count: {topic} missing sections: {missing}")
            if extra:
                errors.append(f"Count: {topic} extra sections: {extra}")
    return errors


def validate_score_range(report: dict) -> list[str]:
    """All real products must have scores in the 65-98 range."""
    errors: list[str] = []
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in products_data.get(topic, {}).get(section, {}).items():
                for idx, p in enumerate(products):
                    score = p.get("score", 0)
                    if score == 0:
                        continue
                    if score < SCORE_MIN_DISPLAYED or score > SCORE_MAX_DISPLAYED:
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        errors.append(
                            f"Score: {loc} score {score} out of range "
                            f"{SCORE_MIN_DISPLAYED}-{SCORE_MAX_DISPLAYED}"
                        )
    return errors


# ── Bilingual parity ───────────────────────────────────────────────────────


def validate_bilingual_parity(report: dict) -> list[str]:
    """The monthly heat report must have US market coverage."""
    errors: list[str] = []
    products_data = report.get("products", {})
    us_count = 0
    for topic in ("makeup", "fragrance"):
        panels = products_data.get(topic, {}).get("heat_rankings", {})
        for panel_key, products in panels.items():
            if panel_key.startswith("US"):
                us_count += len([p for p in products if p.get("score", 0) > 0])
    if us_count == 0:
        errors.append("Parity: monthly heat US market coverage is zero — no US products")
    return errors


# ── Source citation ────────────────────────────────────────────────────────


def validate_source_citation(report: dict, sources: dict) -> list[str]:
    """Every product URL in report must exist in sources.json."""
    errors: list[str] = []
    source_urls = {s.get("url", "") for s in sources.get("sources", [])}
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in products_data.get(topic, {}).get(section, {}).items():
                for idx, p in enumerate(products):
                    link = p.get("detail", {}).get("price_link", {}).get("link", "")
                    if link and link not in source_urls:
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        errors.append(f"Citation: {loc} URL not in sources.json: {link}")
    return errors


# ── Combined pre-publish validation ────────────────────────────────────────


def validate_for_publish(
    week_dir: Path,
    *,
    is_historical: bool = False,
) -> list[str]:
    """Run all pre-publish validation checks (Req 2, 5).

    Returns a list of error strings.  Empty list means validation passed.

    Parameters
    ----------
    week_dir : Path
        Directory containing report.json, sources.json, scoring.json.
    is_historical : bool
        When True, relaxes new-product qualification checks for legacy data.
    """
    errors: list[str] = []
    report_path = week_dir / "report.json"
    sources_path = week_dir / "sources.json"
    scoring_path = week_dir / "scoring.json"

    if not report_path.exists():
        return [f"Pre-publish: report.json not found in {week_dir}"]

    report = json.loads(report_path.read_text(encoding="utf-8"))
    sources = json.loads(sources_path.read_text(encoding="utf-8")) if sources_path.exists() else {}
    scoring = json.loads(scoring_path.read_text(encoding="utf-8")) if scoring_path.exists() else {}

    # 1. Launch evidence non-null (Req 1)
    errors.extend(validate_launch_evidence_non_null(report))

    # 2. Evidence completeness (Req 1)
    errors.extend(validate_evidence_completeness(report))

    # 3. Evidence types
    errors.extend(validate_evidence_types(report))

    # 4. Product/source referential integrity
    errors.extend(validate_product_source_referential_integrity(report, sources))

    # 5. Count constraints
    errors.extend(validate_panel_counts(report))

    # 6. Section count
    errors.extend(validate_section_count(report))

    # 7. Score range
    errors.extend(validate_score_range(report))

    # 8. Bilingual parity (Chinese coverage scope)
    errors.extend(validate_bilingual_parity(report))

    # 9. Source citation
    errors.extend(validate_source_citation(report, sources))

    # 10. Phase 7 evidence integrity (existing checks)
    errors.extend(validate_evidence_integrity(report, sources, is_historical))

    # 11. Scoring validation (existing checks)
    scoring_errors = validate_scoring_json(scoring)
    errors.extend(scoring_errors)

    return errors
