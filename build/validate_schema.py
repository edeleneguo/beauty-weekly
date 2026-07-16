#!/usr/bin/env python3
"""Schema validation for beauty_weekly models.

Validates data/week28.json against both the legacy schema (exact match)
and the target schema (via the adapter).  Reports migration warnings
and verifies schema metadata for future JSON Schema generation.

Exit code 0 = all pass, 1 = failures found.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.loader import (  # noqa: E402
    LEGACY_ISOLATED_FIELDS,
    MIGRATION_GAPS,
    load_legacy_raw,
    to_target,
)
from beauty_weekly.models import (  # noqa: E402
    LegacyWeeklyReport,
    WeeklyReport,
)

DATA_PATH = os.path.join(ROOT, "data", "week28.json")


def _check_legacy_schema(data: dict) -> list[str]:
    """Validate data against legacy schema with extra forbid."""
    errors = []
    try:
        LegacyWeeklyReport.model_validate(data)
    except Exception as exc:
        errors.append(f"Legacy schema validation failed: {exc}")
        return errors
    return errors


def _check_exact_roundtrip(data: dict) -> list[str]:
    """Verify explicitly present legacy fields reproduce the original JSON."""
    errors = []
    try:
        legacy = LegacyWeeklyReport.model_validate(data)
        dumped = legacy.model_dump(mode="json", exclude_unset=True)
        if dumped != data:
            errors.append("Legacy roundtrip mismatch: model_dump != original JSON")
    except Exception as exc:
        errors.append(f"Roundtrip check failed: {exc}")
    return errors


def _check_target_mapping(data: dict) -> tuple[WeeklyReport, list[str], list[str]]:
    """Validate legacy → target mapping and collect warnings."""
    errors = []
    warnings = []
    try:
        legacy = LegacyWeeklyReport.model_validate(data)
        target, warnings = to_target(legacy)
    except Exception as exc:
        errors.append(f"Target mapping failed: {exc}")
        return None, errors, warnings  # type: ignore[return-value]
    return target, errors, warnings


def _check_migration_documentation() -> list[str]:
    """Verify migration gaps and isolated fields are documented."""
    errors = []
    if len(MIGRATION_GAPS) < 2:
        errors.append("MIGRATION_GAPS must have at least 2 entries")
    if len(LEGACY_ISOLATED_FIELDS) < 5:
        errors.append("LEGACY_ISOLATED_FIELDS must have at least 5 entries")
    expected_isolated = {
        "raw_score",
        "version_en_makeup",
        "version_cn_makeup",
        "version_en_fragrance",
        "version_cn_fragrance",
        "category_badge_cn",
    }
    actual_isolated = set(LEGACY_ISOLATED_FIELDS.keys())
    if expected_isolated != actual_isolated:
        errors.append(
            f"LEGACY_ISOLATED_FIELDS mismatch: expected {expected_isolated}, got {actual_isolated}"
        )
    return errors


def _check_schema_metadata() -> list[str]:
    """Verify schema_version and migration_gaps exist in manifest."""
    errors = []
    manifest_path = os.path.join(ROOT, "data", "weeks", "2026-W28", "manifest.json")
    if not os.path.exists(manifest_path):
        errors.append(f"Manifest not found: {manifest_path}")
        return errors
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    if "schema_version" not in manifest:
        errors.append("Manifest missing schema_version")
    if "migration_gaps" not in manifest:
        errors.append("Manifest missing migration_gaps")
    if "legacy_fields_isolated" not in manifest:
        errors.append("Manifest missing legacy_fields_isolated")
    return errors


def main() -> int:
    data = load_legacy_raw(DATA_PATH)
    all_errors: list[str] = []

    print("Schema validation: legacy schema ... ", end="")
    all_errors.extend(_check_legacy_schema(data))
    print("OK" if not all_errors else "FAIL")

    print("Schema validation: exact roundtrip ... ", end="")
    all_errors.extend(_check_exact_roundtrip(data))
    print("OK" if len(all_errors) == 0 else "FAIL")

    print("Schema validation: target mapping ... ", end="")
    target, mapping_errors, warnings = _check_target_mapping(data)
    all_errors.extend(mapping_errors)
    print("OK" if not mapping_errors else "FAIL")

    if warnings:
        print(f"  Migration warnings: {len(warnings)}")

    print("Schema validation: migration documentation ... ", end="")
    all_errors.extend(_check_migration_documentation())
    print("OK" if len(all_errors) == 0 else "FAIL")

    print("Schema validation: manifest metadata ... ", end="")
    all_errors.extend(_check_schema_metadata())
    print("OK" if len(all_errors) == 0 else "FAIL")

    if all_errors:
        print("\n=== Schema Validation Failures ===")
        for e in all_errors:
            print(f"  ERROR: {e}")
        return 1

    print("All schema validation checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
