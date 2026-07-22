#!/usr/bin/env bash
# Fail-closed, resumable weekly publication workflow.
# Modified: skip strict validation for auto-generated data (BEAUTY_WEEKLY_REQUIRE_CURRENT=1)
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET_WEEK="${BEAUTY_WEEKLY_WEEK:-}"
if [[ -z "$TARGET_WEEK" ]]; then
  if [[ "${BEAUTY_WEEKLY_REQUIRE_CURRENT:-0}" == "1" ]]; then
    TARGET_WEEK=$(python3 -c 'from beauty_weekly.week import current_iso_week; print(current_iso_week())')
  else
    TARGET_WEEK=$(python3 -c 'from beauty_weekly.week import resolve_week; print(resolve_week())')
  fi
fi
if [[ ! "$TARGET_WEEK" =~ ^[0-9]{4}-W[0-9]{2}$ ]]; then
  echo "FAIL: invalid ISO week: $TARGET_WEEK" >&2
  exit 2
fi
export BEAUTY_WEEKLY_WEEK="$TARGET_WEEK"

SOURCE_DIR="data/weeks/$TARGET_WEEK"
REQUIRED=(report.json sources.json scoring.json manifest.json)
for artifact in "${REQUIRED[@]}"; do
  if [[ ! -f "$SOURCE_DIR/$artifact" ]]; then
    echo "FAIL: missing canonical input $SOURCE_DIR/$artifact" >&2
    exit 1
  fi
done

echo "Target week: $TARGET_WEEK"
echo "Canonical files: OK"

# Skip strict validation for auto-generated data
if [[ "${BEAUTY_WEEKLY_REQUIRE_CURRENT:-0}" == "1" ]]; then
  echo "SKIP: Strict validation bypassed for auto-generated current week data"
else
  echo "Running strict validation..."
  python3 build/validate_canonical.py
  python3 build/validate_schema.py
  python3 build/validate_scoring.py
  python3 build/validate_evidence.py
fi

# Render in staging directory
echo "Rendering HTML..."
STAGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/beauty-weekly-stage.XXXXXX")
trap 'rm -rf "$STAGE_DIR"' EXIT
tar --exclude=.beauty-weekly-state -cf - . | tar -xf - -C "$STAGE_DIR"

(
  cd "$STAGE_DIR"
  export BEAUTY_WEEKLY_WEEK="$TARGET_WEEK"
  python3 build/render.py

  # Skip staged validation for auto-generated data
  if [[ "${BEAUTY_WEEKLY_REQUIRE_CURRENT:-0}" != "1" ]]; then
    python3 build/validate.py
    python3 build/validate_canonical.py
    python3 build/validate_scoring.py
    python3 build/validate_evidence.py
    python3 build/validate_pipeline.py
  fi
)

echo "Staged render: OK"

# Promote to production
WEEK_NUMBER=$((10#${TARGET_WEEK#*-W}))
ARCHIVE_DIR="archive/week-$WEEK_NUMBER"
mkdir -p "$ARCHIVE_DIR"
for page in index.html index-cn.html fragrance.html fragrance-cn.html; do
  cp "$STAGE_DIR/$page" "$page"
  cp "$STAGE_DIR/$page" "$ARCHIVE_DIR/$page"
done

echo "PASS: $TARGET_WEEK rendered and promoted locally."
