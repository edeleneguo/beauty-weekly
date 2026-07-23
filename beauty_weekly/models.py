"""Canonical data models for Beauty Weekly reports.

Target models define the desired clean schema with ``extra = "forbid"``
and ``strict = True``.  LegacyWeeklyReport captures the *exact* shape
of the current ``data/week28.json`` with ``extra = "forbid"`` for exact
JSON roundtrip — none of its fields are silently discarded.  The adapter
in ``loader.py`` maps between the two and documents migration gaps.

Domain separation (Phase 3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~
The target model is decomposed into five orthogonal concerns:

1. **Stable trend entities** — ``TrendTag``, ``Trend``
2. **Bilingual product fields** — ``LocalizedText``, ``PriceLink``,
   ``Category``
3. **Source / evidence records** — ``Evidence``, ``EvidenceAbsence``
4. **New-product qualification evidence** — ``LaunchEvidence``
5. **Shared scoring data** — embedded in ``Product`` (rank, score,
   market, tier)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ── Enums / Literals ──────────────────────────────────────────────────────────


class Market(str, Enum):
    """Sales market identifier."""

    US = "US"
    CN = "CN"


class Tier(str, Enum):
    """Price tier classification."""

    LUXURY = "LUXURY"
    MASSTIGE = "MASSTIGE"


class TrendBadgeType(str, Enum):
    """Trend badge value used in heat rankings."""

    TREND = "Trend"


class NewBadgeType(str, Enum):
    """New-product badge value."""

    NEW = "New"
    NEW_UPPER = "NEW"


class QuarantineStatus(str, Enum):
    """Radar quarantine / verification status."""

    VERIFIED = "verified"
    OUT_OF_WINDOW = "out-of-window"
    UNVERIFIED = "unverified"


# ── Localized text ────────────────────────────────────────────────────────────


class LocalizedText(BaseModel):
    """Bilingual text pair — every user-visible string carries both EN and CN."""

    en: str = Field(min_length=1)
    cn: str = Field(min_length=1)

    model_config = {"strict": True, "extra": "forbid"}


# ── Price link ────────────────────────────────────────────────────────────────


class PriceLink(LocalizedText):
    """Display text with a direct product URL.

    Note: some legacy products have empty link fields (migration gap).
    The target model allows empty links; strict link validation is a
    future-phase concern.
    """

    link: str = ""

    model_config = {"strict": True, "extra": "forbid"}


# ── Trend tag (stable bilingual pair) ───────────────────────────────────────


class TrendTag(BaseModel):
    """Bilingual trend tag pair — the stable identity of a trend.

    A ``TrendTag`` is a shared vocabulary element: every product tagged
    with the same trend references the same ``TrendTag`` (e.g.
    ``"Skincare Foundation"`` / ``"养肤底妆趋势"``).  Trend tags are
    defined once per issue in the trend taxonomy and referenced by
    multiple products.
    """

    en: str = Field(min_length=1)
    cn: str = Field(min_length=1)

    model_config = {"strict": True, "extra": "forbid"}


# ── Evidence / Source ─────────────────────────────────────────────────────────


class Evidence(BaseModel):
    """Provenance of a radar product claim.

    All fields are required and non-null.  Unsupported claims (missing
    title, published_at, fetched_at, or supported_fields) cause a
    validation failure rather than silently accepting incomplete evidence.
    """

    url: str = Field(min_length=1, description="Direct product-page URL")
    title: str = Field(min_length=1, description="Title of the source page or article")
    type: str = Field(description="Evidence category (e.g. review, launch-announcement)")
    published_at: str = Field(
        min_length=1,
        description="ISO-8601 date/time the source was published",
    )
    fetched_at: str = Field(
        min_length=1,
        description="ISO-8601 timestamp when evidence was fetched/verified",
    )
    checked_at: str = Field(description="ISO-8601 timestamp of verification")
    supported_fields: list[str] = Field(
        min_length=1,
        description="List of product fields this evidence supports (e.g. price, features, buzz)",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_evidence_completeness(self) -> Evidence:
        """Fail-closed: reject evidence with empty required strings."""
        for field_name in ("url", "title", "type", "published_at", "fetched_at", "checked_at"):
            val = getattr(self, field_name)
            if isinstance(val, str) and not val.strip():
                raise ValueError(f"Evidence.{field_name} must be non-empty")
        if not self.supported_fields:
            raise ValueError("Evidence.supported_fields must contain at least one field name")
        valid_fields = {"price", "features", "buzz", "brand", "category", "launch_date", "link"}
        for sf in self.supported_fields:
            if sf not in valid_fields:
                raise ValueError(
                    f"Evidence.supported_fields contains unsupported field '{sf}' — "
                    f"must be one of: {', '.join(sorted(valid_fields))}"
                )
        return self


class EvidenceAbsence(BaseModel):
    """Explicit marker for absent evidence.

    When evidence cannot be provided, the adapter records *why* rather
    than silently leaving the field ``None``.  This makes data gaps
    queryable and auditable.
    """

    reason: str = Field(min_length=1, description="Why evidence is absent")
    gap_type: str = Field(description="Category: no_url | vague_date | no_evidence | generic_url")

    model_config = {"extra": "forbid"}


# ── Launch / qualification evidence ──────────────────────────────────────────


class LaunchEvidence(BaseModel):
    """Quarantine + launch metadata for a new-product radar item.

    Only fragrance radar products carry these fields today.  Makeup
    radar products have **no** launch-evidence fields in the legacy data
    and will have ``LaunchEvidence = None`` in the target model.

    ``launch_date`` accepts ISO-8601 date strings (``YYYY-MM-DD``) as
    well as vague legacy values (``2026-H1``).  When evidence is absent,
    ``absence_markers`` records *why* explicitly.
    """

    launch_date: str = Field(description="ISO date YYYY-MM-DD or vague legacy value")
    quarantine_status: QuarantineStatus
    quarantine_reason: str | None = None
    evidence: Evidence | None = None
    absence_markers: list[EvidenceAbsence] = Field(default_factory=list)
    evidence_grade: Literal["A", "B", "C"] | None = None
    date_basis: Literal[
        "official_launch",
        "first_listing",
        "source_publication",
        "first_verified_mention",
    ] | None = None

    model_config = {"extra": "forbid"}


# ── Trend ─────────────────────────────────────────────────────────────────────


class Trend(BaseModel):
    """Trend metadata for a trend-badge product.

    In the legacy JSON these live as flat fields on the product
    (``trend_id``, ``trend_tag``, ``trend_tag_cn``, ``trend_rationale``).
    The target model groups them under a single ``Trend`` object.

    For radar products, all four fields are populated from the flat
    legacy fields.  For heat products, the adapter falls back to
    extracting ``tag`` / ``tag_cn`` from ``key_features.trend_tags``
    and derives ``id`` deterministically; ``rationale`` is ``None``
    because heat products never carry a rationale field.
    """

    id: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    tag_cn: str = Field(min_length=1)
    rationale: str | None = None

    model_config = {"extra": "forbid"}


# ── Category ──────────────────────────────────────────────────────────────────


class Category(BaseModel):
    """Category badge with optional Chinese translation."""

    en: str
    cn: str | None = None

    model_config = {"extra": "forbid"}


# ── Product detail ────────────────────────────────────────────────────────────


class ProductDetail(BaseModel):
    """The four detail cells rendered for every product."""

    price_link: PriceLink
    key_features: LocalizedText
    buzz: LocalizedText
    brand: LocalizedText

    model_config = {"strict": True, "extra": "forbid"}


# ── Score explainability ─────────────────────────────────────────────────────


class ScoreComponent(BaseModel):
    """One weighted component in the product score explanation."""

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    weight: float = Field(gt=0, le=1)
    max_points: int = Field(ge=1, le=100)
    points: int = Field(ge=0, le=100)
    evidence: str = Field(min_length=1)

    model_config = {"strict": True, "extra": "forbid"}


class ScoreBreakdown(BaseModel):
    """Weighted explanation for a displayed score.

    Current historical monthly scores remain non-recomputable from raw platform
    data. This block explains the displayed score using the agreed dashboard
    weights, while preserving the original ``score`` as the source of truth.
    """

    methodology: str = Field(min_length=1)
    recomputable: bool
    total: int = Field(ge=0, le=100)
    components: list[ScoreComponent] = Field(min_length=4, max_length=4)

    model_config = {"strict": True, "extra": "forbid"}

    @model_validator(mode="after")
    def _validate_component_totals(self) -> ScoreBreakdown:
        if sum(component.points for component in self.components) != self.total:
            raise ValueError("ScoreBreakdown component points must sum to total")
        if round(sum(component.weight for component in self.components), 10) != 1.0:
            raise ValueError("ScoreBreakdown component weights must sum to 1.0")
        for component in self.components:
            if component.points > component.max_points:
                raise ValueError(
                    f"ScoreBreakdown component {component.id} exceeds max_points"
                )
        return self


class DataQuality(BaseModel):
    """Dashboard field/source coverage metadata for one product."""

    source_type: str = Field(min_length=1)
    link_type: str = Field(min_length=1)
    coverage_score: int = Field(ge=0, le=100)
    coverage: dict[str, bool] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    note: str = Field(min_length=1)

    model_config = {"strict": True, "extra": "forbid"}


# ── Product (target) ─────────────────────────────────────────────────────────


class Product(BaseModel):
    """A single product record in the target canonical model.

    Legacy-only fields (``raw_score``, ``name_cn``, ``category_badge_cn``,
    embedded ``trend_tags`` inside ``key_features``) are documented but
    represented through the legacy adapter — they are **not** promoted to
    required target-model fields.
    """

    rank: int = Field(ge=1, le=10)
    market: Market
    tier: Tier
    name: str
    name_cn: str | None = None
    category_badge: str
    score: int = Field(ge=0, le=100)
    detail: ProductDetail
    trend_badge: TrendBadgeType | None = None
    new_badge: NewBadgeType | None = None
    # Target sub-objects (populated by adapter when legacy data provides them)
    launch_evidence: LaunchEvidence | None = None
    trend: Trend | None = None
    score_breakdown: ScoreBreakdown | None = None
    data_quality: DataQuality | None = None

    model_config = {"strict": True, "extra": "forbid"}


# ── WeeklyReport (target) ────────────────────────────────────────────────────

PANEL_KEYS = Literal["US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"]


class SectionProducts(BaseModel):
    """Products for one section (heat or radar), keyed by panel."""

    heat_rankings: dict[str, list[Product]] = Field(default_factory=dict)
    new_product_radar: dict[str, list[Product]] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class Products(BaseModel):
    """Products grouped by topic (makeup / fragrance)."""

    makeup: SectionProducts = Field(default_factory=SectionProducts)
    fragrance: SectionProducts = Field(default_factory=SectionProducts)

    model_config = {"extra": "forbid"}


class WeeklyReport(BaseModel):
    """Target canonical report model.

    The legacy JSON has additional per-topic version strings
    (``version_en_makeup``, etc.) that are isolated in the legacy
    adapter and not promoted to this target model.
    """

    week: int = Field(ge=1, le=53)
    date_range: str
    date_range_cn: str
    version: str
    products: Products

    model_config = {"strict": True, "extra": "forbid"}


class MonthlyReport(BaseModel):
    """Target canonical monthly report model.

    Mirrors WeeklyReport structure but uses month identifier instead of week.
    """

    month: str = Field(description="YYYY-MM month identifier")
    date_range: str
    date_range_cn: str
    version: str
    products: Products

    model_config = {"strict": True, "extra": "forbid"}


# ══════════════════════════════════════════════════════════════════════════════
# Legacy models — exact shape of current data/week28.json
# ══════════════════════════════════════════════════════════════════════════════


class LegacyLocalizedText(BaseModel):
    """Legacy bilingual text cell — may carry embedded trend_tags."""

    en: str
    cn: str
    trend_tags: list[str] | None = None
    trend_tags_cn: list[str] | None = None

    model_config = {"extra": "forbid"}


class LegacyPriceLink(BaseModel):
    en: str
    cn: str
    link: str

    model_config = {"extra": "forbid"}


class LegacyProductDetail(BaseModel):
    price_link: LegacyPriceLink
    key_features: LegacyLocalizedText
    buzz: LegacyLocalizedText
    brand: LegacyLocalizedText

    model_config = {"extra": "forbid"}


class LegacyProduct(BaseModel):
    """Exact shape of a product record in the legacy JSON.

    All optional fields that appear in some but not all products are
    represented explicitly — none are silently discarded via
    ``model_config = {extra = \"allow\"}``.
    """

    rank: int
    market: str
    tier: str
    name: str
    name_cn: str | None = None
    category_badge: str
    category_badge_cn: str | None = None
    score: int
    raw_score: int | None = None
    detail: LegacyProductDetail
    # Heat badges
    trend_badge: str | None = None
    new_badge: str | None = None
    # Fragrance radar metadata (absent on makeup radar)
    quarantine_status: str | None = None
    quarantine_reason: str | None = None
    launch_date: str | None = None
    evidence_url: str | None = None
    evidence_type: str | None = None
    evidence_checked_at: str | None = None
    # Trend metadata (flat on product, not nested)
    trend_id: str | None = None
    trend_tag: str | None = None
    trend_tag_cn: str | None = None
    trend_rationale: str | None = None

    model_config = {"extra": "forbid"}


class LegacySectionProducts(BaseModel):
    heat_rankings: dict[str, list[LegacyProduct]] = Field(default_factory=dict)
    new_product_radar: dict[str, list[LegacyProduct]] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class LegacyProducts(BaseModel):
    makeup: LegacySectionProducts = Field(default_factory=LegacySectionProducts)
    fragrance: LegacySectionProducts = Field(default_factory=LegacySectionProducts)

    model_config = {"extra": "forbid"}


class LegacyWeeklyReport(BaseModel):
    """Exact shape of data/week28.json — the backward-compatible model.

    Every field present in the legacy JSON is represented here.
    Migration gaps vs the target model are documented in the adapter
    (``loader.py``).
    """

    week: int
    date_range: str
    date_range_cn: str
    version: str
    version_en_makeup: str | None = None
    version_cn_makeup: str | None = None
    version_en_fragrance: str | None = None
    version_cn_fragrance: str | None = None
    products: LegacyProducts

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_panel_keys(self) -> LegacyWeeklyReport:
        """Ensure panel keys are the canonical four."""
        valid_panels = {"US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"}
        for section_name in ("heat_rankings", "new_product_radar"):
            for topic_name in ("makeup", "fragrance"):
                section = getattr(self.products, topic_name)
                panels = getattr(section, section_name)
                for key in panels:
                    if key not in valid_panels:
                        raise ValueError(
                            f"Invalid panel key '{key}' in {topic_name}.{section_name}"
                        )
        return self
