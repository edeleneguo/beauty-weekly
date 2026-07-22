#!/usr/bin/env python3
"""deploy_pages.py — Deploy rendered HTML to GitHub Pages and verify.

Pushes the 4 root HTML files + archive to GitHub repo via Contents API,
triggers Pages build, and verifies 3-layer consistency (raw → build → CDN).

Environment variables:
  GITHUB_TOKEN — GitHub PAT with repo:write permission (required)
  TARGET_WEEK  — ISO week string (auto-calculated if not set)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.week import resolve_week  # noqa: E402

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "edeleneguo/beauty-weekly"
BRANCH = "main"
PAGES = ["index.html", "index-cn.html", "fragrance.html", "fragrance-cn.html"]


def api_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Make a GitHub API request."""
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "beauty-weekly-deploy",
        "Accept": "application/vnd.github+json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body_text)
        except json.JSONDecodeError:
            return e.code, {"raw": body_text[:500]}


def upload_file(filename: str, local_path: Path) -> bool:
    """Upload a single file to the repo via Contents API."""
    if not local_path.exists():
        print(f"  {filename}: SKIP (not found)")
        return False

    # Get current SHA for update
    status, resp = api_request("GET", f"/repos/{REPO}/contents/{filename}")
    sha = resp.get("sha") if status == 200 else None

    import base64

    content = base64.b64encode(local_path.read_bytes()).decode("ascii")
    payload = {
        "message": f"Weekly update: {filename}",
        "content": content,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    status, resp = api_request("PUT", f"/repos/{REPO}/contents/{filename}", payload)
    if status in (200, 201):
        print(f"  {filename}: DEPLOYED ({status})")
        return True
    else:
        print(f"  {filename}: FAILED ({status}) {json.dumps(resp)[:200]}")
        return False


def trigger_pages_build() -> bool:
    """Trigger a GitHub Pages build."""
    status, resp = api_request("POST", f"/repos/{REPO}/pages/builds")
    if status == 201:
        print("  Pages build triggered")
        return True
    else:
        print(f"  Pages build trigger: {status} (may already be building)")
        return False


def verify_version(url: str) -> str | None:
    """Fetch a URL and extract the version meta tag."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "beauty-weekly-verify"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # Look for version meta tag or week marker
            import re

            m = re.search(r'<meta\s+name=["\']version["\']\s+content=["\']([^"\']+)["\']', html)
            if m:
                return m.group(1)
            # Fallback: look for Week number in title
            m = re.search(r"Week\s+(\d+)", html)
            if m:
                return f"week{m.group(1)}"
            return "unknown"
    except Exception as e:
        return f"ERROR: {e}"


def main() -> int:
    if not TOKEN:
        print("FATAL: GITHUB_TOKEN not set")
        return 1

    iso_week = resolve_week()
    week_num = int(iso_week.split("-W")[1])

    print("=== GitHub Pages Deployment ===")
    print(f"ISO Week: {iso_week} (Week {week_num})")
    print(f"Repo: {REPO}")
    print()

    # Step 1: Upload 4 root HTML files
    print("--- Step 1: Upload HTML files ---")
    all_ok = True
    for fname in PAGES:
        local_path = ROOT / fname
        if not upload_file(fname, local_path):
            all_ok = False

    # Upload archive files
    archive_dir = ROOT / "archive" / f"week-{week_num}"
    if archive_dir.exists():
        print("  Uploading archive files...")
        for fname in PAGES:
            archive_path = archive_dir / fname
            if archive_path.exists():
                api_path = f"/repos/{REPO}/contents/archive/week-{week_num}/{fname}"
                status, resp = api_request("GET", api_path)
                sha = resp.get("sha") if status == 200 else None
                import base64

                content = base64.b64encode(archive_path.read_bytes()).decode("ascii")
                payload = {
                    "message": f"Archive week-{week_num}: {fname}",
                    "content": content,
                    "branch": BRANCH,
                }
                if sha:
                    payload["sha"] = sha
                status, resp = api_request("PUT", api_path, payload)
                result = "OK" if status in (200, 201) else "FAIL"
                print(f"    archive/week-{week_num}/{fname}: {result}")

    if not all_ok:
        print("\nDEPLOY FAILED: Some files failed to upload")
        return 1

    # Step 2: Trigger Pages build
    print("\n--- Step 2: Trigger Pages build ---")
    trigger_pages_build()

    # Step 3: Wait for CDN propagation
    print("\n--- Step 3: Wait for CDN propagation (60s) ---")
    for i in range(60, 0, -10):
        print(f"  Waiting... {i}s remaining")
        time.sleep(10)

    # Step 4: 3-layer verification
    print("\n--- Step 4: 3-Layer Verification ---")
    all_verified = True
    for fname in PAGES:
        local_version = verify_version(f"file://{ROOT / fname}") or "unknown"
        raw_url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{fname}?v={int(time.time())}"
        cdn_url = f"https://edeleneguo.github.io/beauty-weekly/{fname}?v={int(time.time())}"

        raw_version = verify_version(raw_url)
        cdn_version = verify_version(cdn_url)

        raw_match = "✓" if raw_version == local_version else "✗"
        cdn_match = "✓" if cdn_version == local_version else "✗"

        parts = (
            f"  {fname}: local={local_version}"
            f" | raw={raw_version} {raw_match}"
            f" | cdn={cdn_version} {cdn_match}"
        )
        print(parts)

        if raw_version != local_version or cdn_version != local_version:
            all_verified = False

    print()
    if all_verified:
        print("=== DEPLOY VERIFIED: All 3 layers consistent ===")
        print("\nLive URLs:")
        print("  EN Makeup:    https://edeleneguo.github.io/beauty-weekly/")
        print("  CN Makeup:    https://edeleneguo.github.io/beauty-weekly/index-cn.html")
        print("  EN Fragrance: https://edeleneguo.github.io/beauty-weekly/fragrance.html")
        print("  CN Fragrance: https://edeleneguo.github.io/beauty-weekly/fragrance-cn.html")
        return 0
    else:
        print("=== VERIFICATION FAILED: CDN may still be propagating ===")
        print("Re-run this script after 60s to re-check.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
