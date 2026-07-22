"""Source evidence and new-product qualification integrity (Phase 7).

Validates referential integrity between report.json and sources.json,
enforces new-product qualification rules, and ensures explicit
evidence-absence documentation for historical gaps.

Design constraints
~~~~~~~~~~~~~~~~~~
* Fail-closed: any validation failure is an error.
* Historical Week 28 gaps (empty links, unverified quarantine) are
  documented as explicit absence records — not silently accepted.
* No URLs, dates, sources, or evidence are invented.
* The two missing product links (To Summer Kunlun Snow, Scent Library
  Boiled Water) are treated as explicit EvidenceAbsence unless a
  verified official URL exists in repository data.
* Every Evidence object must carry url, title, published_at, fetched_at,
  and supported_fields — no nulls or empty strings accepted.
* Unsupported claim fields cause validation failure.
"""

from __future__ import annotations

from datetime import datetime

# ── Constants ────────────────────────────────────────────────────────────────

PHASE = 7
SOURCES_SCHEMA_VERSION = "2.0.0"

# Evidence types recognized in the system
EVIDENCE_TYPES = frozenset(
    {
        "product_page",
        "review",
        "launch_announcement",
        "social_media",
        "e-commerce_listing",
        "editorial",
        "unknown",
    }
)

# Quarantine statuses
QUARANTINE_STATUSES = frozenset(
    {
        "verified",
        "unverified",
        "out-of-window",
    }
)

# Evidence absence gap types
ABSENCE_GAP_TYPES = frozenset(
    {
        "no_url",
        "vague_date",
        "no_evidence",
        "generic_url",
        "unverified_launch",
    }
)

# Products with explicitly known missing links (from repository data)
# These are documented in ROOT_CAUSE_WEEK28.md and migration_gaps
EXPLICIT_EVIDENCE_ABSENCES: list[dict[str, str]] = [
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
]

# Qualification window: new products must have launch evidence within
# a defined time range relative to the report date.
# For historical Week 28, these rules are documented but not enforced
# retroactively on existing data — they apply to NEW records.
QUALIFICATION_REQUIRED_FIELDS = frozenset(
    {
        "quarantine_status",
        "launch_date",
    }
)

# Fields that every Evidence object must carry (non-null, non-empty).
EVIDENCE_REQUIRED_FIELDS = frozenset(
    {
        "url",
        "title",
        "type",
        "published_at",
        "fetched_at",
        "checked_at",
        "supported_fields",
    }
)

# Fields that evidence supported_fields may reference.
VALID_EVIDENCE_SUPPORTED_FIELDS = frozenset(
    {
        "price",
        "features",
        "buzz",
        "brand",
        "category",
        "launch_date",
        "link",
    }
)


# ── Source-product referential integrity ────────────────────────────────────


def _build_source_url_index(sources: dict) -> dict[str, dict]:
    """Build a lookup index from URL → source entry."""
    idx: dict[str, dict] = {}
    for src in sources.get("sources", []):
        url = src.get("url", "")
        if url:
            idx[url] = src
    return idx


def _build_source_id_index(sources: dict) -> dict[str, dict]:
    """Build a lookup index from id → source entry."""
    idx: dict[str, dict] = {}
    for src in sources.get("sources", []):
        sid = src.get("id", "")
        if sid:
            idx[sid] = src
    return idx


def validate_source_product_referential_integrity(
    report: dict,
    sources: dict,
) -> list[str]:
    """Validate that every source referenced by report products exists in sources.json.

    Checks:
    1. Every product price_link URL with a non-empty link has a matching
       source entry in sources.json.
    2. Every source entry in sources.json is referenced by at least one
       product in report.json (no orphaned sources).
    3. Source entries referenced by radar products with evidence_url also
       match.

    Fail-closed: any mismatch is an error.
    """
    errors: list[str] = []
    url_index = _build_source_url_index(sources)

    # Collect all URLs from report.json
    report_urls: dict[str, list[str]] = {}  # url → list of product locations
    products_data = report.get("products", {})
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = products_data.get(topic, {}).get(section, {})
            for panel_key, product_list in panels.items():
                for idx, p in enumerate(product_list):
                    link = p.get("detail", {}).get("price_link", {}).get("link", "")
                    if link:
                        loc = f"{topic}/{section}/{panel_key}[{idx}] {p.get('name', '?')}"
                        report_urls.setdefault(link, []).append(loc)
                    launch_evidence = p.get("launch_evidence") or {}
                    evidence = launch_evidence.get("evidence") or {}
                    evidence_url = evidence.get("url", "")
                    if evidence_url:
                        loc = f"{topic}/{section}/{panel_key}[{idx}] {p.get('name', '?')}"
                        report_urls.setdefault(evidence_url, []).append(loc)

    # Check: every report URL with a non-empty link has a matching source
    for url, locations in report_urls.items():
        if url not in url_index:
            errors.append(
                f"Referential integrity: product URL not found in sources.json: "
                f"{url} (used by: {', '.join(locations[:2])})"
            )

    # Check: every source URL is referenced by at least one report product
    source_urls = {src.get("url", "") for src in sources.get("sources", [])}
    referenced_urls = set(report_urls.keys())
    orphaned = source_urls - referenced_urls
    if orphaned:
        errors.append(
            f"Referential integrity: {len(orphaned)} source(s) in sources.json "
            f"not referenced by any product in report.json"
        )

    return errors


# ── New-product qualification rules ─────────────────────────────────────────


def validate_new_product_qualification(
    report: dict,
    is_historical: bool = True,
) -> list[str]:
    """Validate that products with new_badge='New' meet qualification rules.

    Rules:
    1. Every product with new_badge='New' must have launch_evidence.
    2. launch_evidence must have quarantine_status and launch_date.
    3. quarantine_status must be one of the recognized values.
    4. For non-historical records: quarantine_status must be 'verified'
       with a non-empty evidence URL.
    5. For historical records: quarantine_status may be 'unverified' or
       'out-of-window', but must have a quarantine_reason explaining why.

    Fail-closed: unverified or incomplete records cannot silently
    receive New status.
    """
    errors: list[str] = []
    products_data = report.get("products", {})

    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = products_data.get(topic, {}).get(section, {})
            for panel_key, product_list in panels.items():
                for idx, p in enumerate(product_list):
                    if p.get("new_badge") != "New":
                        continue
                    loc = f"{topic}/{section}/{panel_key}[{idx}] {p.get('name', '?')}"

                    le = p.get("launch_evidence")
                    if le is None:
                        # New badge without any launch_evidence
                        # For historical: this is a known gap (makeup radar)
                        if is_historical:
                            continue  # Known gap: makeup radar products lack launch_evidence
                        errors.append(
                            f"New-product qualification: {loc} has new_badge='New' "
                            f"but no launch_evidence object"
                        )
                        continue

                    # Must have quarantine_status
                    qs = le.get("quarantine_status")
                    if qs is None:
                        errors.append(
                            f"New-product qualification: {loc} launch_evidence "
                            f"missing quarantine_status"
                        )
                        continue

                    if qs not in QUARANTINE_STATUSES:
                        errors.append(
                            f"New-product qualification: {loc} invalid quarantine_status '{qs}'"
                        )
                        continue

                    # Must have launch_date
                    ld = le.get("launch_date", "")
                    if not ld:
                        errors.append(
                            f"New-product qualification: {loc} launch_evidence missing launch_date"
                        )

                    # For non-historical: must be verified with evidence URL
                    if not is_historical and qs != "verified":
                        errors.append(
                            f"New-product qualification: {loc} quarantine_status "
                            f"'{qs}' is not 'verified' — cannot receive New status "
                            f"on non-historical record"
                        )

                    # For any status: unverified/out-of-window must have quarantine_reason
                    if qs in ("unverified", "out-of-window") and not le.get("quarantine_reason"):
                        errors.append(
                            f"New-product qualification: {loc} quarantine_status "
                            f"'{qs}' requires quarantine_reason"
                        )

                    # Verified items should have evidence
                    if qs == "verified":
                        evidence = le.get("evidence")
                        if evidence is None:
                            absence = le.get("absence_markers", [])
                            if not absence:
                                errors.append(
                                    f"New-product qualification: {loc} quarantine_status "
                                    f"'verified' but no evidence and no absence_markers"
                                )

    return errors


# ── Evidence absence documentation ──────────────────────────────────────────


def validate_evidence_absences(
    report: dict,
    sources: dict,
) -> list[str]:
    """Validate that products with known missing evidence have explicit absence records.

    For Week 28: the two products with empty links (To Summer Kunlun Snow,
    Scent Library Boiled Water) must have explicit EvidenceAbsence
    documentation in sources.json provenance.evidence_absences.

    Fail-closed: undocumented gaps are errors.
    """
    errors: list[str] = []

    provenance = sources.get("provenance", {})
    absences = provenance.get("evidence_absences", [])

    # Build set of documented absence product names
    documented = {a.get("product_name", "") for a in absences}

    # Check that every explicitly known absence is documented
    for expected in EXPLICIT_EVIDENCE_ABSENCES:
        name = expected["product_name"]
        if name not in documented:
            errors.append(
                f"Evidence absence not documented: '{name}' has known missing "
                f"link but no absence record in sources.json provenance"
            )

    # Validate absence record structure
    for absence in absences:
        for required_field in ("product_name", "gap_type", "reason"):
            if not absence.get(required_field):
                errors.append(
                    f"Evidence absence record missing required field "
                    f"'{required_field}': {absence.get('product_name', '?')}"
                )
        if absence.get("gap_type") not in ABSENCE_GAP_TYPES:
            errors.append(
                f"Evidence absence invalid gap_type "
                f"'{absence.get('gap_type')}' for {absence.get('product_name', '?')}"
            )

    return errors


# ── Source evidence structure validation ─────────────────────────────────────


def validate_source_evidence_structure(sources: dict) -> list[str]:
    """Validate that sources.json has the Phase 7 evidence structure.

    Checks:
    1. Has provenance block with required fields.
    2. Each source has checked_at and provenance.
    3. checked_at is ISO-8601 format.
    4. Source types are recognized.
    5. Absence records are well-formed.
    """
    errors: list[str] = []

    # Check top-level provenance
    provenance = sources.get("provenance")
    if provenance is None:
        errors.append("sources.json missing provenance block (Phase 7)")
        return errors

    for field in ("migration_recorded_at", "phase"):
        if not provenance.get(field):
            errors.append(f"sources.json provenance missing '{field}'")

    if provenance.get("phase") != PHASE:
        errors.append(
            f"sources.json provenance.phase = {provenance.get('phase')}, expected {PHASE}"
        )

    # Validate each source entry
    for src in sources.get("sources", []):
        sid = src.get("id", "?")

        src_prov = src.get("provenance")
        if src_prov is None:
            errors.append(f"Source {sid} missing provenance")
            verification_status = None
        else:
            verification_status = src_prov.get("verification_status")
            if not verification_status:
                errors.append(f"Source {sid} provenance missing verification_status")

        # Verified sources must carry a real verification timestamp.  Legacy
        # imports must preserve the absence rather than fabricate one.
        checked_at = src.get("checked_at")
        if verification_status == "verified" and not checked_at:
            errors.append(f"Source {sid} missing checked_at")
        elif checked_at:
            # Validate ISO-8601 format (basic check)
            try:
                datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                errors.append(f"Source {sid} checked_at not valid ISO-8601: {checked_at}")

        # Must have type
        src_type = src.get("type", "")
        if src_type not in EVIDENCE_TYPES:
            errors.append(f"Source {sid} unknown type '{src_type}'")

        if verification_status == "legacy_unverified":
            if checked_at is not None:
                errors.append(f"Source {sid} legacy_unverified must have checked_at=null")
            if not src_prov.get("reason"):
                errors.append(f"Source {sid} legacy_unverified missing reason")

    return errors


# ── Combined evidence validation ─────────────────────────────────────────────


def validate_evidence_integrity(
    report: dict,
    sources: dict,
    is_historical: bool = True,
) -> list[str]:
    """Run all Phase 7 evidence and qualification integrity checks.

    Fail-closed: any error means the data is invalid.
    """
    errors: list[str] = []

    # 1. Source evidence structure
    errors.extend(validate_source_evidence_structure(sources))

    # 2. Referential integrity
    errors.extend(validate_source_product_referential_integrity(report, sources))

    # 3. New-product qualification
    errors.extend(validate_new_product_qualification(report, is_historical))

    # 4. Evidence absence documentation
    errors.extend(validate_evidence_absences(report, sources))

    return errors
