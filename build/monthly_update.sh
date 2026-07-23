#!/usr/bin/env bash
# Fail-closed, resumable monthly publication workflow.
# Always runs strict validation — no exceptions for auto-generated data.
# Pre-publish validation ensures stable Pages (Req 5).
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET_MONTH="${BEAUTY_MONTHLY_MONTH:-}"
if [[ -z "$TARGET_MONTH" ]]; then
  TARGET_MONTH=$(python3 -c 'from beauty_weekly.month import resolve_month; print(resolve_month())')
fi
if [[ ! "$TARGET_MONTH" =~ ^[0-9]{4}-[0-9]{2}$ ]]; then
  echo "FAIL: invalid month: $TARGET_MONTH" >&2
  exit 2
fi
export BEAUTY_MONTHLY_MONTH="$TARGET_MONTH"

SOURCE_DIR=$(python3 -c "from beauty_weekly.month import month_data_dir; print(month_data_dir('$TARGET_MONTH'))")
REQUIRED=(report.json sources.json scoring.json manifest.json)
for artifact in "${REQUIRED[@]}"; do
  if [[ ! -f "$SOURCE_DIR/$artifact" ]]; then
    echo "FAIL: missing canonical input $SOURCE_DIR/$artifact" >&2
    exit 1
  fi
done

echo "Target month: $TARGET_MONTH"
echo "Canonical files: OK"

echo "Running strict validation..."
python3 build/validate_canonical.py
python3 build/validate_schema.py
python3 build/validate_scoring.py
python3 build/validate_evidence.py

# Pre-publish validation (Req 2): launch evidence, counts, parity, citation
echo "Running pre-publish validation..."
python3 build/validate_published.py

# Render in staging directory
echo "Rendering HTML..."
STAGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/beauty-monthly-stage.XXXXXX")
trap 'rm -rf "$STAGE_DIR"' EXIT
tar --exclude=.beauty-weekly-state -cf - . | tar -xf - -C "$STAGE_DIR"

(
  cd "$STAGE_DIR"
  export BEAUTY_MONTHLY_MONTH="$TARGET_MONTH"
  python3 build/render.py

  # Staged validation: always runs (no skip)
  python3 build/validate.py
  python3 build/validate_canonical.py
  python3 build/validate_scoring.py
  python3 build/validate_evidence.py
  python3 build/validate_pipeline.py
)

echo "Staged render: OK"

# Promote to production
for page in index.html fragrance.html; do
  cp "$STAGE_DIR/$page" "$page"
done

# Save manifest hash proof for online verification (Req 6)
MANIFEST_HASH=$(python3 -c "
import json, hashlib, sys
with open('$SOURCE_DIR/manifest.json') as f:
    m = json.load(f)
print(m.get('canonical_hash', ''))
")
echo "Manifest hash: $MANIFEST_HASH"
echo "$MANIFEST_HASH" > ".deploy-manifest-hash"

echo "PASS: $TARGET_MONTH rendered and promoted locally."
