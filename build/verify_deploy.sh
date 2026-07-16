#!/usr/bin/env bash
# verify_deploy.sh – Download each deployed page and compare full SHA256 hash
# against the local file. Retries transient failures up to 3 times.
#
# Usage: ./build/verify_deploy.sh [base_url]
set -euo pipefail

BASE_URL="${1:-https://edeleneguo.github.io/beauty-weekly}"
FILES=("index.html" "index-cn.html" "fragrance.html" "fragrance-cn.html")
PASS=0
FAIL=0
MAX_RETRIES=3
RETRY_DELAY=2
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

for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "[ERROR] $f  missing locally"
        FAIL=$((FAIL + 1))
        continue
    fi

    local_hash=$(sha256 "$f")
    echo -n "$f  local=$local_hash  "

    remote_url="$BASE_URL/$f"
    remote_hash=$(download_hash "$remote_url" 2>"$ERROR_LOG") || {
        echo ""
        echo "  [DOWNLOAD FAILED] could not fetch $remote_url after $MAX_RETRIES attempts"
        cat "$ERROR_LOG" 2>/dev/null || true
        FAIL=$((FAIL + 1))
        continue
    }

    echo -n "remote=$remote_hash  "

    if [ "$local_hash" = "$remote_hash" ]; then
        echo "[OK]"
        PASS=$((PASS + 1))
    else
        echo "[MISMATCH]"
        echo "  local sha256:  $local_hash"
        echo "  remote sha256: $remote_hash"
        echo "  diff -u <(curl -sS '$remote_url') '$f'  # manual diff hint"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
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
