#!/usr/bin/env bash
# Single, fail-closed local and CI quality gate.
#
# Supports both historical weekly fixture mode (CI pinned to a frozen
# W28 snapshot) and monthly reporting mode (BEAUTY_MONTHLY_MONTH set).
# Validates freshly rendered output in isolation — never reads
# stale committed HTML.  The monthly-deploy production path (which writes
# to ROOT and promotes to archive/) is preserved unchanged.
set -euo pipefail

cd "$(dirname "$0")/.."

export BEAUTY_MONTHLY_MONTH="${BEAUTY_MONTHLY_MONTH:-}"

FILES=(index.html fragrance.html)

# hash_files_in DIR — hash the four output files under DIR.
hash_files_in() {
    local dir="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$dir" && sha256sum "${FILES[@]}")
    elif command -v shasum >/dev/null 2>&1; then
        (cd "$dir" && shasum -a 256 "${FILES[@]}")
    else
        echo "FAIL: no SHA256 utility available" >&2
        return 2
    fi
}

# ── Static / data-level checks (no HTML involved) ──────────────────────
python3 build/check_secrets.py
python3 -m ruff check .
python3 -m pytest -q
python3 build/validate_schema.py
python3 build/validate_canonical.py
python3 build/validate_scoring.py
python3 build/validate_evidence.py

# In historical-fixture mode (e.g. CI pinned to a frozen W28 snapshot) the
# three checks below depend on a live production pipeline that is not
# available, so skip them.
if [ "${BEAUTY_WEEKLY_HISTORICAL_FIXTURE:-0}" != "1" ]; then
    python3 build/validate_published.py
    python3 build/validate_pipeline.py
    python3 build/check_parity.py
fi

# ── Fresh render into a staging directory ───────────────────────────────
STAGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/beauty-weekly-check.XXXXXX")
trap 'rm -rf "$STAGE_DIR"' EXIT

export BEAUTY_WEEKLY_OUTPUT_DIR="$STAGE_DIR"
python3 build/render.py

# ── Validate the freshly rendered HTML in isolation ─────────────────────
python3 build/validate.py

# ── Deterministic render: two consecutive renders must be identical ─────
FIRST=$(mktemp "${TMPDIR:-/tmp}/beauty-weekly-first.XXXXXX")
SECOND=$(mktemp "${TMPDIR:-/tmp}/beauty-weekly-second.XXXXXX")
trap 'rm -rf "$STAGE_DIR" "$FIRST" "$SECOND"' EXIT

hash_files_in "$STAGE_DIR" >"$FIRST"
python3 build/render.py
hash_files_in "$STAGE_DIR" >"$SECOND"
diff -u "$FIRST" "$SECOND"

if [ "${BEAUTY_WEEKLY_HISTORICAL_FIXTURE:-0}" = "1" ]; then
    echo "PASS: secrets, lint, tests, validation, scoring, evidence, and deterministic render (historical fixture / monthly mode)"
else
    echo "PASS: secrets, lint, tests, validation, scoring, evidence, pipeline, parity, and deterministic render"
fi
