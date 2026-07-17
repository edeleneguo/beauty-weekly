#!/usr/bin/env bash
# Single, fail-closed local and CI quality gate.
set -euo pipefail

cd "$(dirname "$0")/.."

FILES=(index.html index-cn.html fragrance.html fragrance-cn.html)
BEFORE=$(mktemp "${TMPDIR:-/tmp}/beauty-weekly-before.XXXXXX")
FIRST=$(mktemp "${TMPDIR:-/tmp}/beauty-weekly-first.XXXXXX")
trap 'rm -f "$BEFORE" "$FIRST"' EXIT

hash_files() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "${FILES[@]}"
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "${FILES[@]}"
    else
        echo "FAIL: no SHA256 utility available" >&2
        return 2
    fi
}

python3 build/check_secrets.py
python3 -m ruff check .
python3 -m pytest -q
python3 build/validate_schema.py
python3 build/validate.py
python3 build/validate_canonical.py
python3 build/validate_scoring.py
python3 build/validate_evidence.py
python3 build/validate_pipeline.py
python3 build/check_parity.py

hash_files >"$BEFORE"
python3 build/render.py
hash_files >"$FIRST"
python3 build/render.py
hash_files | diff -u "$FIRST" -
diff -u "$BEFORE" "$FIRST"
git diff --exit-code -- "${FILES[@]}"

echo "PASS: secrets, lint, tests, validation, scoring, evidence, pipeline, parity, and deterministic render"
