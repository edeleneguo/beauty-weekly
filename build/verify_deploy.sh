#!/usr/bin/env bash
# verify_deploy.sh – Compare git working tree, GitHub Pages, and content hashes.
# Usage: ./build/verify_deploy.sh [base_url]
set -euo pipefail

BASE_URL="${1:-https://edeleneguo.github.io/beauty-weekly}"
FILES=("index.html" "index-cn.html" "fragrance.html" "fragrance-cn.html")
PASS=0
FAIL=0

hash_file() { sha256sum "$1" | cut -d' ' -f1; }

echo "=== Deployment Verification ==="
echo "Base URL: $BASE_URL"
echo ""

for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "[ERROR] $f missing locally"
        FAIL=$((FAIL+1))
        continue
    fi

    local_hash=$(hash_file "$f")
    echo -n "$f  local=$local_hash  "

    # Fetch remote
    remote_hash=$(curl -sL "$BASE_URL/$f" | sha256sum | cut -d' ' -f1)
    echo -n "remote=$remote_hash  "

    if [ "$local_hash" = "$remote_hash" ]; then
        echo "[OK]"
        PASS=$((PASS+1))
    else
        echo "[MISMATCH]"
        FAIL=$((FAIL+1))
    fi
done

echo ""
echo "--- Summary ---"
echo "PASS: $PASS"
echo "FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
