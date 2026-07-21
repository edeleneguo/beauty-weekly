#!/usr/bin/env python3
"""Hard parity guard: verify canonical → legacy adapter output equals legacy data.

Fail-closed: exit 1 if any divergence is detected between the canonical
dataset (``data/weeks/<iso_week>/report.json``) transformed through the
lossless compatibility adapter and the original legacy file
(``data/week28.json``).

Comparison rules:
  1. Every field present in the adapted output must match the legacy value.
  2. Fields present ONLY in legacy (``name_en``, ``category_badge_cn``,
     ``raw_score``, version-per-topic strings) are NOT produced by the
     adapter — they are the renderer's ``.get()`` fallback domain and are
     intentionally omitted from comparison.
  3. ``trend_id`` / ``trend_tag`` / ``trend_tag_cn`` / ``trend_rationale``
     are only compared for radar sections (the adapter only flattens trend
     for new_product_radar).  Heat products never had these flat fields.
  4. Two known empty-link gaps on CN MASSTIGE fragrance are exempted.

Usage:
    python3 build/check_parity.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.canonical_adapter import canonical_to_legacy  # noqa: E402
from beauty_weekly.loader import load_legacy_raw  # noqa: E402
from beauty_weekly.week import resolve_week, weeks_dir  # noqa: E402

_weeks_dir_name = resolve_week()
WEEKS_DIR = weeks_dir(_weeks_dir_name)
LEGACY_PATH = Path(ROOT) / "data" / "week28.json"

# Top-level fields that the canonical model preserves.
TOP_LEVEL_FIELDS = {"week", "date_range", "date_range_cn", "version"}

# Flat product fields that must always match.
# Detail fields and evidence fields are mandatorily compared for ALL products.
MANDATORY_FLAT_FIELDS = [
    "rank",
    "market",
    "tier",
    "name",
    "category_badge",
    "score",
    "trend_badge",
    "new_badge",
]

# Evidence-related fields (compared for all products via .get()).
EVIDENCE_FLAT_FIELDS = [
    "quarantine_status",
    "quarantine_reason",
    "launch_date",
    "evidence_url",
    "evidence_type",
    "evidence_checked_at",
]

# Trend flat fields (only compared for radar sections).
TREND_FLAT_FIELDS = [
    "trend_id",
    "trend_tag",
    "trend_tag_cn",
    "trend_rationale",
]

# Detail cell sub-field paths.
DETAIL_PATHS = [
    ("price_link", "en"),
    ("price_link", "cn"),
    ("price_link", "link"),
    ("key_features", "en"),
    ("key_features", "cn"),
    ("key_features", "trend_tags"),
    ("key_features", "trend_tags_cn"),
    ("buzz", "en"),
    ("buzz", "cn"),
    ("brand", "en"),
    ("brand", "cn"),
]

# Known empty-link products — exempted from link comparison.
EMPTY_LINK_NAMES = {"To Summer Kunlun Snow", "Scent Library Boiled Water"}


def _compare_products(legacy: dict, adapted: dict, errors: list[str]) -> None:
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            is_radar = section == "new_product_radar"
            legacy_panels = legacy.get("products", {}).get(topic, {}).get(section, {})
            adapted_panels = adapted.get("products", {}).get(topic, {}).get(section, {})

            for panel_key in ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"):
                legacy_list = legacy_panels.get(panel_key, [])
                adapted_list = adapted_panels.get(panel_key, [])

                if len(legacy_list) != len(adapted_list):
                    errors.append(
                        f"{topic}/{section}/{panel_key}: product count mismatch "
                        f"legacy={len(legacy_list)} adapted={len(adapted_list)}"
                    )
                    continue

                for i, (lp, ap) in enumerate(zip(legacy_list, adapted_list)):
                    loc = f"{topic}/{section}/{panel_key}[{i}]"

                    # Compare mandatory flat fields
                    for field in MANDATORY_FLAT_FIELDS:
                        lv = lp.get(field)
                        av = ap.get(field)
                        if lv != av:
                            errors.append(
                                f"{loc}: '{field}' mismatch: legacy={repr(lv)} adapted={repr(av)}"
                            )

                    # Compare evidence fields (may be None in both)
                    for field in EVIDENCE_FLAT_FIELDS:
                        lv = lp.get(field)
                        av = ap.get(field)
                        if lv != av:
                            errors.append(
                                f"{loc}: '{field}' mismatch: legacy={repr(lv)} adapted={repr(av)}"
                            )

                    # Compare trend flat fields (radar only)
                    if is_radar:
                        for field in TREND_FLAT_FIELDS:
                            lv = lp.get(field)
                            av = ap.get(field)
                            if lv != av:
                                errors.append(
                                    f"{loc}: '{field}' mismatch: "
                                    f"legacy={repr(lv)} adapted={repr(av)}"
                                )

                    # Compare detail cells
                    for dkey, subkey in DETAIL_PATHS:
                        lv = lp.get("detail", {}).get(dkey, {}).get(subkey)
                        av = ap.get("detail", {}).get(dkey, {}).get(subkey)
                        if lv != av:
                            # Exempt empty links
                            if (
                                dkey == "price_link"
                                and subkey == "link"
                                and lp.get("name") in EMPTY_LINK_NAMES
                            ):
                                continue
                            errors.append(
                                f"{loc}: detail.{dkey}.{subkey} mismatch: "
                                f"legacy={repr(lv)} adapted={repr(av)}"
                            )

                    # Compare name_cn if present in either
                    if "name_cn" in lp or "name_cn" in ap:
                        lv = lp.get("name_cn")
                        av = ap.get("name_cn")
                        if lv != av:
                            errors.append(
                                f"{loc}: 'name_cn' mismatch: legacy={repr(lv)} adapted={repr(av)}"
                            )


def _compare_top_level(legacy: dict, adapted: dict, errors: list[str]) -> None:
    for field in TOP_LEVEL_FIELDS:
        lv = legacy.get(field)
        av = adapted.get(field)
        if lv != av:
            errors.append(f"Top-level '{field}' mismatch: legacy={repr(lv)} adapted={repr(av)}")


def main() -> int:
    print("Parity guard: canonical → legacy adapter ... ", end="")

    legacy = load_legacy_raw(LEGACY_PATH)

    canonical_path = WEEKS_DIR / "report.json"
    if not canonical_path.exists():
        print("FAIL")
        print(f"  ERROR: Canonical report not found: {canonical_path}")
        return 1

    with open(canonical_path, encoding="utf-8") as f:
        canonical = json.load(f)

    try:
        adapted = canonical_to_legacy(canonical)
    except Exception as exc:
        print("FAIL")
        print(f"  ERROR: Adapter failed: {exc}")
        return 1

    errors: list[str] = []

    _compare_top_level(legacy, adapted, errors)
    _compare_products(legacy, adapted, errors)

    if errors:
        print("FAIL")
        print(f"  Found {len(errors)} divergence(s):")
        for e in errors:
            print(f"    {e}")
        return 1

    print("OK")
    print(
        "  Compared top-level fields + products across 4 sections x 4 panels x all business fields."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
