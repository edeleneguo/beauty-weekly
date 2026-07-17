#!/usr/bin/env python3
"""Generate canonical weekly dataset from legacy data.

Phase 4: produces report.json, sources.json, scoring.json under
data/weeks/2026-W28/ from data/week28.json.

Run once after Phase 3 baseline is established.
"""

import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beauty_weekly.canonical import (  # noqa: E402
    _deterministic_json,
    _sha256_of,
    generate_canonical_report,
    generate_scoring_model,
    generate_sources,
)
from beauty_weekly.loader import load_legacy_report  # noqa: E402

WEEKS_DIR = Path(ROOT) / "data" / "weeks" / "2026-W28"


def main() -> int:
    WEEKS_DIR.mkdir(parents=True, exist_ok=True)

    legacy = load_legacy_report("data/week28.json")
    print("Loaded legacy data: week", legacy.week)

    # 1. Generate canonical report
    report_dict, warnings = generate_canonical_report(legacy)
    report_json = _deterministic_json(report_dict)
    report_path = WEEKS_DIR / "report.json"
    report_path.write_text(report_json, encoding="utf-8")
    print(f"  report.json: {len(report_json)} bytes, {len(warnings)} warnings")

    # 2. Generate sources
    sources = generate_sources(legacy)
    sources_json = _deterministic_json(sources)
    sources_path = WEEKS_DIR / "sources.json"
    sources_path.write_text(sources_json, encoding="utf-8")
    print(f"  sources.json: {len(sources_json)} bytes, {sources['total_sources']} sources")

    # 3. Generate scoring model
    scoring = generate_scoring_model(legacy)
    scoring_json = _deterministic_json(scoring)
    scoring_path = WEEKS_DIR / "scoring.json"
    scoring_path.write_text(scoring_json, encoding="utf-8")
    print(f"  scoring.json: {len(scoring_json)} bytes, recomputable={scoring['recomputable']}")

    # 4. Compute hashes
    report_hash = _sha256_of(report_json)
    sources_hash = _sha256_of(sources_json)
    scoring_hash = _sha256_of(scoring_json)

    # 5. Load and update manifest (preserve Phase 3 fields)
    manifest_path = WEEKS_DIR / "manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    manifest["schema_version"] = 3
    manifest["phase"] = "7"
    manifest["canonical_hash"] = report_hash
    manifest["sources_hash"] = sources_hash
    manifest["scoring_hash"] = scoring_hash
    manifest["remaining_warnings"] = len(warnings)
    manifest["note"] = (
        "Phase 7: canonical weekly dataset with truthful legacy source provenance, "
        "reproducible scoring model (non-recomputable for legacy data), and "
        "lossless adapter-generated report.json."
    )

    manifest_json = _deterministic_json(manifest)
    manifest_path.write_text(manifest_json, encoding="utf-8")
    print(f"  manifest.json: schema_version=3, {len(manifest_json)} bytes")

    print("\nCanonical dataset generated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
