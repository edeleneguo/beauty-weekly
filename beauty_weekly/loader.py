"""Backward-compatible loader and adapter for legacy week data.

Usage::

    from beauty_weekly.loader import load_legacy_report, to_target

    legacy = load_legacy_report("data/week28.json")
    target, warnings = to_target(legacy)   # maps to target WeeklyReport
    report, warnings = load_report("data/week28.json")  # legacy → target in one call

The adapter documents every migration gap explicitly — it never
fabricates fields that the legacy data does not provide.  Warnings
are surfaced for missing links, vague dates, and other gaps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from beauty_weekly.models import (
    Evidence,
    EvidenceAbsence,
    LaunchEvidence,
    LegacyLocalizedText,
    LegacyProduct,
    LegacySectionProducts,
    LegacyWeeklyReport,
    LocalizedText,
    Market,
    NewBadgeType,
    PriceLink,
    Product,
    ProductDetail,
    Products,
    QuarantineStatus,
    SectionProducts,
    Tier,
    Trend,
    TrendBadgeType,
    WeeklyReport,
)

_ROOT = Path(__file__).resolve().parent.parent


# ── Loader ────────────────────────────────────────────────────────────────────


def load_legacy_report(path: str | Path) -> LegacyWeeklyReport:
    """Load and validate a legacy JSON file into ``LegacyWeeklyReport``.

    Raises ``pydantic.ValidationError`` if the JSON does not match the
    legacy schema.  All fields are explicitly represented — nothing is
    silently discarded.
    """
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    return LegacyWeeklyReport.model_validate(raw)


def load_legacy_raw(path: str | Path) -> dict:
    """Load the raw JSON dict (no validation)."""
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── Adapter: Legacy → Target ─────────────────────────────────────────────────

# Explicit list of fields that exist in the legacy model but have NO
# direct representation in the target model.  These are *not* fabricated
# during the mapping — they are isolated and documented.
LEGACY_ISOLATED_FIELDS = {
    "raw_score": "Legacy score clamping hint — not promoted to target model",
    "version_en_makeup": "Per-topic version string — not in target WeeklyReport",
    "version_cn_makeup": "Per-topic version string — not in target WeeklyReport",
    "version_en_fragrance": "Per-topic version string — not in target WeeklyReport",
    "version_cn_fragrance": "Per-topic version string — not in target WeeklyReport",
    "category_badge_cn": "Chinese category label — not promoted to target Category model",
}

# Fields that the legacy data *never* provides for certain product types,
# causing the target model to have None for those sub-objects.
MIGRATION_GAPS = {
    "makeup.radar.launch_evidence": (
        "Makeup radar products have no quarantine_status, launch_date, "
        "evidence_url, evidence_type, or evidence_checked_at fields in "
        "the legacy data.  LaunchEvidence will be None for all makeup "
        "radar products."
    ),
    "makeup.radar.trend_metadata_on_non_trend": (
        "Non-trend makeup radar products have no trend_id/trend_tag/etc. "
        "fields.  TrendMetadata will be None."
    ),
    "trend_tags_in_key_features": (
        "In the legacy data, trend_tags and trend_tags_cn are embedded "
        "inside the key_features detail cell (LegacyLocalizedText), not "
        "as standalone Trend model fields.  The adapter extracts them "
        "into Trend.tag / Trend.tag_cn when a product has trend_badge."
    ),
}

_VAGUE_DATE_RE = re.compile(
    r"^(\d{4}-H[12]|\d{4}-Q[1-4]|\d{4}-\d{2}$|"
    r"Q[1-4]\s+\d{4}|(Early|Mid|Late)\s+)",
    re.I,
)


def _map_legacy_trend(lp: LegacyProduct) -> Trend | None:
    """Extract a Trend from legacy product fields.

    Radar products carry flat ``trend_id`` / ``trend_tag`` /
    ``trend_tag_cn`` / ``trend_rationale`` fields.  Heat products carry
    ``trend_tags`` / ``trend_tags_cn`` embedded inside
    ``detail.key_features`` instead.

    The adapter first tries flat fields; when they are absent it falls
    back to ``key_features.trend_tags`` and derives ``id``
    deterministically.  ``rationale`` is ``None`` for heat products
    because they never carry a rationale field.

    Returns ``None`` only when no trend data is available at all.
    """
    if not lp.trend_badge:
        return None

    # Prefer flat fields (radar products have these)
    if lp.trend_id and lp.trend_tag and lp.trend_tag_cn:
        return Trend(
            id=lp.trend_id,
            tag=lp.trend_tag,
            tag_cn=lp.trend_tag_cn,
            rationale=lp.trend_rationale or None,
        )

    # Fall back to key_features trend_tags (heat products have these)
    kf = lp.detail.key_features
    en_tags = kf.trend_tags or []
    cn_tags = kf.trend_tags_cn or []
    if en_tags and cn_tags:
        tag = en_tags[0]
        tag_cn = cn_tags[0]
        # Deterministic id derivation from canonical tag name
        trend_id = "trend_" + tag.lower().replace(" ", "_").replace("-", "_")
        return Trend(
            id=trend_id,
            tag=tag,
            tag_cn=tag_cn,
            rationale=None,
        )

    return None


def _map_legacy_launch_evidence(lp: LegacyProduct) -> LaunchEvidence | None:
    """Extract LaunchEvidence from flat legacy fields.

    Returns ``None`` when the product has no ``quarantine_status``
    (typical for makeup radar products).

    When evidence is partially absent (e.g. missing URL or vague date),
    ``EvidenceAbsence`` markers record *why* explicitly.
    """
    if lp.quarantine_status is None:
        return None
    qs = QuarantineStatus(lp.quarantine_status)
    evidence = None
    absence_markers: list[EvidenceAbsence] = []

    if lp.evidence_url and lp.evidence_type and lp.evidence_checked_at:
        evidence = Evidence(
            url=lp.evidence_url,
            type=lp.evidence_type,
            checked_at=lp.evidence_checked_at,
        )
    else:
        # Document what is absent
        if not lp.evidence_url:
            absence_markers.append(
                EvidenceAbsence(
                    reason="No evidence URL provided in legacy data",
                    gap_type="no_url",
                )
            )
        if not lp.evidence_type:
            absence_markers.append(
                EvidenceAbsence(
                    reason="No evidence type provided in legacy data",
                    gap_type="no_evidence",
                )
            )
        if not lp.evidence_checked_at:
            absence_markers.append(
                EvidenceAbsence(
                    reason="No evidence verification timestamp provided",
                    gap_type="no_evidence",
                )
            )

    # Vague dates produce an absence marker (informational, not blocking)
    if lp.launch_date and _VAGUE_DATE_RE.match(lp.launch_date):
        absence_markers.append(
            EvidenceAbsence(
                reason=f"Launch date '{lp.launch_date}' is not exact ISO-8601",
                gap_type="vague_date",
            )
        )

    return LaunchEvidence(
        launch_date=lp.launch_date or "",
        quarantine_status=qs,
        quarantine_reason=lp.quarantine_reason,
        evidence=evidence,
        absence_markers=absence_markers,
    )


def _map_legacy_key_features(kf: LegacyLocalizedText) -> LocalizedText:
    """Map a legacy key_features cell to target LocalizedText.

    Legacy key_features may carry ``trend_tags`` / ``trend_tags_cn``.
    These are extracted by the Trend adapter and NOT embedded in the
    target ``LocalizedText`` — the target model keeps them in the
    ``Trend`` sub-object instead.
    """
    return LocalizedText(en=kf.en, cn=kf.cn)


def _map_legacy_product(lp: LegacyProduct) -> Product:
    """Map a single legacy product to the target Product model.

    Migration gaps documented in ``MIGRATION_GAPS``.
    """
    detail = ProductDetail(
        price_link=PriceLink(
            en=lp.detail.price_link.en,
            cn=lp.detail.price_link.cn,
            link=lp.detail.price_link.link,
        ),
        key_features=_map_legacy_key_features(lp.detail.key_features),
        buzz=LocalizedText(en=lp.detail.buzz.en, cn=lp.detail.buzz.cn),
        brand=LocalizedText(en=lp.detail.brand.en, cn=lp.detail.brand.cn),
    )

    trend_badge = None
    if lp.trend_badge:
        trend_badge = TrendBadgeType(lp.trend_badge)

    new_badge = None
    if lp.new_badge:
        new_badge = NewBadgeType(lp.new_badge)

    return Product(
        rank=lp.rank,
        market=Market(lp.market),
        tier=Tier(lp.tier),
        name=lp.name,
        name_cn=lp.name_cn,
        category_badge=lp.category_badge,
        score=lp.score,
        detail=detail,
        trend_badge=trend_badge,
        new_badge=new_badge,
        launch_evidence=_map_legacy_launch_evidence(lp),
        trend=_map_legacy_trend(lp),
    )


def _map_legacy_section(sec: LegacySectionProducts) -> SectionProducts:
    """Map a legacy section (heat + radar) to the target model."""
    return SectionProducts(
        heat_rankings={
            panel: [_map_legacy_product(p) for p in products]
            for panel, products in sec.heat_rankings.items()
        },
        new_product_radar={
            panel: [_map_legacy_product(p) for p in products]
            for panel, products in sec.new_product_radar.items()
        },
    )


def _collect_warnings(legacy: LegacyWeeklyReport) -> list[str]:
    """Collect migration warnings for the legacy → target mapping.

    Phase 3: trend metadata for heat products is extracted from
    ``key_features.trend_tags`` when flat fields are absent — no
    warning is emitted because the data is present and verifiable.

    Remaining warnings are genuine data gaps (e.g. empty links on
    Chinese niche fragrances with no public e-commerce URL).
    """
    warnings: list[str] = []
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            lps = getattr(getattr(legacy.products, topic), section)
            for panel, products in lps.items():
                for lp in products:
                    loc = f"{topic}/{section}/{panel}/{lp.name}"
                    # Missing / empty links — genuine data gap
                    if not lp.detail.price_link.link:
                        warnings.append(f"{loc}: empty link (migration gap)")
                    # Vague launch dates on verified items
                    if (
                        lp.quarantine_status == "verified"
                        and lp.launch_date
                        and _VAGUE_DATE_RE.match(lp.launch_date)
                    ):
                        warnings.append(
                            f"{loc}: vague launch_date '{lp.launch_date}' "
                            f"on verified item — exact ISO date required"
                        )
                    # Missing evidence on verified items
                    if lp.quarantine_status == "verified" and not lp.evidence_url:
                        warnings.append(f"{loc}: verified item missing evidence_url")
    return warnings


def to_target(legacy: LegacyWeeklyReport) -> tuple[WeeklyReport, list[str]]:
    """Convert a ``LegacyWeeklyReport`` to the target ``WeeklyReport``.

    Returns ``(report, warnings)`` where warnings document migration gaps.
    No fields are fabricated — missing data surfaces as None or warnings.
    """
    warnings = _collect_warnings(legacy)
    return WeeklyReport(
        week=legacy.week,
        date_range=legacy.date_range,
        date_range_cn=legacy.date_range_cn,
        version=legacy.version,
        products=Products(
            makeup=_map_legacy_section(legacy.products.makeup),
            fragrance=_map_legacy_section(legacy.products.fragrance),
        ),
    ), warnings


# ── Convenience ───────────────────────────────────────────────────────────────


def load_report(path: str | Path) -> tuple[WeeklyReport, list[str]]:
    """Load legacy JSON and return target ``WeeklyReport`` + migration warnings."""
    return to_target(load_legacy_report(path))


def validate_legacy(path: str | Path) -> list[str]:
    """Validate a legacy JSON file and return any migration warnings.

    Returns an empty list if the data loads cleanly.
    """
    errors: list[str] = []
    try:
        legacy = load_legacy_report(path)
        _target, warnings = to_target(legacy)
    except Exception as exc:
        errors.append(str(exc))
        return errors

    return warnings
