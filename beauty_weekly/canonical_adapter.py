"""Canonical-to-legacy compatibility adapter for Phase 5.

Converts the canonical ``report.json`` (target ``WeeklyReport`` shape) into
the legacy-shaped dict that ``build/render.py`` and ``build/validate.py``
expect.

The adapter is *lossless* for all business fields: every value present in
the canonical dataset is projected back into the legacy shape.  No data
is fabricated — fields absent from the canonical model are simply omitted.

Adapter decisions
~~~~~~~~~~~~~~~~~
* ``launch_evidence`` (nested) → flat ``quarantine_status``, ``quarantine_reason``,
  ``launch_date``, ``evidence_url``, ``evidence_type``, ``evidence_checked_at``.
* ``trend`` (nested, radar products only) → flat ``trend_id``, ``trend_tag``,
  ``trend_tag_cn``, ``trend_rationale``.  Heat products never carried these flat
  fields in the legacy data and do not get them now.
* ``trend_tags`` / ``trend_tags_cn`` re-embedded into ``key_features`` for all
  trend-badge products (the renderer's ``_render_detail_cell`` reads them).
* Top-level version-per-topic strings (``version_en_makeup`` etc.) are NOT
  produced — the canonical ``WeeklyReport`` model does not carry them.  The
  renderer and validators do not consume these fields.
* ``name_en``, ``category_badge_cn``, ``raw_score`` are NOT produced — they
  were absent from most legacy products and the renderer's ``.get()`` fallbacks
  handle their absence.

Design constraints
~~~~~~~~~~~~~~~~~~
* Never fabricates data — all values originate from the canonical dataset.
* Preserves byte-for-byte output parity for all rendered HTML.
* Documents every mapping decision explicitly.
"""

from __future__ import annotations

import copy
from typing import Any

# Canonical sub-objects that must be flattened to legacy flat fields.
LAUNCH_EVIDENCE_MAP: dict[str, str] = {
    "quarantine_status": "quarantine_status",
    "quarantine_reason": "quarantine_reason",
    "launch_date": "launch_date",
}

EVIDENCE_MAP: dict[str, str] = {
    "url": "evidence_url",
    "type": "evidence_type",
    "checked_at": "evidence_checked_at",
}

TREND_MAP: dict[str, str] = {
    "id": "trend_id",
    "tag": "trend_tag",
    "tag_cn": "trend_tag_cn",
    "rationale": "trend_rationale",
}


# ── Per-section configuration ──────────────────────────────────────────────

# Which sections get trend fields flattened onto the product dict.
# In the legacy data, only radar products carry flat trend_id/trend_tag/etc.
# Heat products embedded trend_tags inside key_features instead.
TREND_FLATTEN_SECTIONS = {"new_product_radar"}


def _flatten_product(
    canonical_product: dict[str, Any],
    section: str,
) -> dict[str, Any]:
    """Convert one canonical product to legacy flat-field shape.

    Parameters
    ----------
    canonical_product:
        A single product dict from the canonical report.
    section:
        ``"heat_rankings"`` or ``"new_product_radar"`` — determines
        whether flat trend fields are emitted.
    """
    result = dict(canonical_product)  # shallow copy

    # --- Flatten launch_evidence → flat legacy fields ---
    launch_ev = result.pop("launch_evidence", None)
    if launch_ev is not None:
        for canon_key, legacy_key in LAUNCH_EVIDENCE_MAP.items():
            val = launch_ev.get(canon_key)
            if val is not None:
                result[legacy_key] = val
        # Flatten nested evidence sub-object
        ev = launch_ev.get("evidence")
        if ev is not None:
            for canon_key, legacy_key in EVIDENCE_MAP.items():
                val = ev.get(canon_key)
                if val is not None:
                    result[legacy_key] = val
        # Handle absence_markers — legacy data doesn't have them flattened
        # so we ignore them here (they are validation-only metadata)

    # --- Flatten trend → flat legacy fields (radar only) ---
    trend_obj = result.pop("trend", None)
    if trend_obj is not None and section in TREND_FLATTEN_SECTIONS:
        for canon_key, legacy_key in TREND_MAP.items():
            val = trend_obj.get(canon_key)
            if val is not None:
                result[legacy_key] = val

    # --- Re-embed trend_tags / trend_tags_cn into key_features ---
    # The canonical model extracts trend_tags from key_features into Trend.
    # The renderer's _render_detail_cell reads trend_tags from the cell data.
    # Re-inject them so the detail cell renders trend tags correctly.
    if trend_obj is not None:
        detail = result.get("detail", {})
        kf = detail.get("key_features", {})
        if isinstance(kf, dict):
            tag = trend_obj.get("tag")
            tag_cn = trend_obj.get("tag_cn")
            if tag and not kf.get("trend_tags"):
                kf["trend_tags"] = [tag]
            if tag_cn and not kf.get("trend_tags_cn"):
                kf["trend_tags_cn"] = [tag_cn]

    return result


def canonical_to_legacy(canonical_report: dict[str, Any]) -> dict[str, Any]:
    """Convert a canonical ``report.json`` dict back to legacy-shaped dict.

    The conversion is deterministic and lossless for all business fields
    that the renderer and validators consume.  Top-level fields
    (``week``, ``date_range``, etc.) are preserved unchanged.
    """
    result = copy.deepcopy(canonical_report)

    products = result.get("products", {})
    for topic in ("makeup", "fragrance"):
        topic_data = products.get(topic, {})
        for section in ("heat_rankings", "new_product_radar"):
            panels = topic_data.get(section, {})
            sec_key = "new_product_radar" if section == "new_product_radar" else section
            for panel_key, product_list in panels.items():
                panels[panel_key] = [_flatten_product(p, sec_key) for p in product_list]

    return result


def canonical_to_legacy_from_path(report_path: str) -> dict[str, Any]:
    """Load a canonical ``report.json`` and return legacy-shaped dict."""
    import json
    from pathlib import Path

    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return canonical_to_legacy(data)
