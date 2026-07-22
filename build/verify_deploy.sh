#!/usr/bin/env bash
# verify_deploy.sh – Download each deployed page and compare full SHA256 hash
# against the local file. Retries transient failures up to 3 times.
# Optionally verifies ISO week in content and manifest SHA256 hashes.
#
# Usage: ./build/verify_deploy.sh [base_url] [--manifest deploy-manifest.json] [--week 2026-W30]
set -euo pipefail

BASE_URL=""
MANIFEST=""
EXPECTED_WEEK=""
FILES=("index.html" "index-cn.html" "fragrance.html" "fragrance-cn.html")
PASS=0
FAIL=0
MAX_RETRIES=3
RETRY_DELAY=2

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest)
            MANIFEST="$2"
            shift 2
            ;;
        --week)
            EXPECTED_WEEK="$2"
            shift 2
            ;;
        *)
            if [ -z "$BASE_URL" ]; then
                BASE_URL="$1"
            fi
            shift
            ;;
    esac
done

BASE_URL="${BASE_URL:-https://edeleneguo.github.io/beauty-weekly}"

ERROR_LOG=$(mktemp "${TMPDIR:-/tmp}/beauty-weekly-verify.XXXXXX")
trap 'rm -f "$ERROR_LOG"' EXIT

# Portable SHA256: use shasum -a 256 on macOS, sha256sum on Linux
if command -v sha256sum &>/dev/null; then
    sha256() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum &>/dev/null; then
    sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
    echo "FATAL: no sha256sum or shasum found" >&2
    exit 2
fi

sha256_stdin() {
    if command -v sha256sum &>/dev/null; then
        sha256sum | cut -d' ' -f1
    else
        shasum -a 256 | cut -d' ' -f1
    fi
}

echo "=== Deployment Verification ==="
echo "Base URL: $BASE_URL"
echo "Retries:  $MAX_RETRIES"
if [ -n "$MANIFEST" ]; then
    echo "Manifest: $MANIFEST"
fi
if [ -n "$EXPECTED_WEEK" ]; then
    echo "Week:     $EXPECTED_WEEK"
fi
echo ""

download_hash() {
    local url="$1"
    local attempt=1
    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        if hash=$(curl -sS -L --fail --max-time 30 "$url" 2>/dev/null | sha256_stdin); then
            echo "$hash"
            return 0
        fi
        echo "  retry $attempt/$MAX_RETRIES for $url (sleeping ${RETRY_DELAY}s)..." >&2
        sleep "$RETRY_DELAY"
        attempt=$((attempt + 1))
    done
    return 1
}

download_content() {
    local url="$1"
    local attempt=1
    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        if content=$(curl -sS -L --fail --max-time 30 "$url" 2>/dev/null); then
            echo "$content"
            return 0
        fi
        echo "  retry $attempt/$MAX_RETRIES for $url (sleeping ${RETRY_DELAY}s)..." >&2
        sleep "$RETRY_DELAY"
        attempt=$((attempt + 1))
    done
    return 1
}

# Load manifest if provided (bash 3.2 compatible — no associative arrays)
MANIFEST_TMP=$(mktemp "${TMPDIR:-/tmp}/beauty-weekly-manifest.XXXXXX")
trap 'rm -f "$ERROR_LOG" "$MANIFEST_TMP"' EXIT
MANIFEST_COUNT=0
if [ -n "$MANIFEST" ] && [ -f "$MANIFEST" ]; then
    python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for name, info in data.get('artifacts', {}).items():
    print(f'{name}={info[\"sha256\"]}')
" "$MANIFEST" > "$MANIFEST_TMP"
    MANIFEST_COUNT=$(wc -l < "$MANIFEST_TMP")
    echo "Loaded manifest with $MANIFEST_COUNT artifact hashes"
    echo ""
fi

manifest_hash_for() {
    local name="$1"
    grep "^${name}=" "$MANIFEST_TMP" 2>/dev/null | head -1 | cut -d= -f2- || true
}

for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "[ERROR] $f  missing locally"
        FAIL=$((FAIL + 1))
        continue
    fi

    local_hash=$(sha256 "$f")
    echo -n "$f  local=$local_hash  "

    remote_url="$BASE_URL/$f"

    # Get remote hash
    remote_hash=$(download_hash "$remote_url" 2>"$ERROR_LOG") || {
        echo ""
        echo "  [DOWNLOAD FAILED] could not fetch $remote_url after $MAX_RETRIES attempts"
        cat "$ERROR_LOG" 2>/dev/null || true
        FAIL=$((FAIL + 1))
        continue
    }

    echo -n "remote=$remote_hash  "

    # Compare local vs remote hash
    hash_ok=true
    if [ "$local_hash" = "$remote_hash" ]; then
        echo -n "[OK]  "
    else
        echo -n "[MISMATCH]  "
        echo ""
        echo "  local sha256:  $local_hash"
        echo "  remote sha256: $remote_hash"
        hash_ok=false
    fi

    # Verify against manifest hash if available
    mhash=$(manifest_hash_for "$f")
    if [ -n "$mhash" ]; then
        manifest_hash="$mhash"
        if [ "$remote_hash" = "$manifest_hash" ]; then
            echo -n "[MANIFEST OK]  "
        else
            echo ""
            echo "  manifest sha256: $manifest_hash"
            echo "  remote sha256:   $remote_hash"
            echo "  [MANIFEST MISMATCH]"
            hash_ok=false
        fi
    fi

    # Verify ISO week in content if expected week is set
    if [ -n "$EXPECTED_WEEK" ]; then
        week_num=$(echo "$EXPECTED_WEEK" | sed 's/.*-W//')
        content=$(download_content "$remote_url" 2>"$ERROR_LOG") || {
            echo ""
            echo "  [CONTENT DOWNLOAD FAILED] for week verification"
            FAIL=$((FAIL + 1))
            continue
        }
        if echo "$content" | grep -q "Week ${week_num}" 2>/dev/null; then
            echo -n "[WEEK OK]  "
        else
            echo ""
            echo "  expected Week ${week_num} in content but not found"
            hash_ok=false
        fi
    fi

    if $hash_ok; then
        echo "[PASS]"
        PASS=$((PASS + 1))
    else
        echo "[FAIL]"
        FAIL=$((FAIL + 1))
    fi
    echo ""
done

echo "--- Summary ---"
echo "PASS: $PASS"
echo "FAIL: $FAIL"
if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "RESULT: FAIL – $FAIL file(s) did not match deployment"
    exit 1
fi
echo ""
echo "RESULT: PASS – all $PASS files match deployment"
exit 0
