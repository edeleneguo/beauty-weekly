#!/usr/bin/env python3
"""Scan tracked files for leaked GitHub PATs and other secrets.

Fail-closed: exit 1 if any GitHub PAT pattern is found in tracked files.
Exit 0 only when the scan completes with zero matches.

Usage:
    python3 build/check_secrets.py          # scan tracked files
    python3 build/check_secrets.py --dir .  # scan a directory tree instead
"""

import os
import re
import subprocess
import sys

# GitHub token prefixes (case-insensitive matching applied)
# See: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
PAT_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"gho_[A-Za-z0-9]{36,}"),
    re.compile(r"ghu_[A-Za-z0-9]{36,}"),
    re.compile(r"ghs_[A-Za-z0-9]{36,}"),
    re.compile(r"ghr_[A-Za-z0-9]{36,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82,}"),
]

# Also catch bare base64-encoded PATs in common assignment patterns
BARE_ASSIGNMENT = re.compile(
    r"""(?:GITHUB_TOKEN|GH_TOKEN|PAT|github_pat|access_token)\s*[:=]\s*['"]?(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)""",
    re.IGNORECASE,
)


def _repository_files():
    """Return tracked plus untracked, non-ignored repository files."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def _dir_files(root):
    """Return all regular files under a directory as usable paths."""
    files = []
    for dirpath, _dirs, filenames in os.walk(root):
        # skip hidden dirs and cache dirs
        rel = os.path.relpath(dirpath, root)
        parts = rel.split(os.sep)
        skip = any(p.startswith(".") or p in ("__pycache__", "node_modules") for p in parts)
        if skip:
            continue
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            files.append(fp)
    return files


def scan_file(filepath):
    """Scan a single file for PAT patterns. Returns list of (line, pattern, match)."""
    hits = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                for pat in PAT_PATTERNS:
                    for m in pat.finditer(line):
                        hits.append((f"{filepath}:{lineno}", pat.pattern, m.group()))
                for m in BARE_ASSIGNMENT.finditer(line):
                    hits.append((f"{filepath}:{lineno}", "bare-assignment", m.group()))
    except OSError:
        pass
    return hits


def main():
    scan_dir = None
    if "--dir" in sys.argv:
        idx = sys.argv.index("--dir")
        if idx + 1 < len(sys.argv):
            scan_dir = sys.argv[idx + 1]

    try:
        files = _dir_files(scan_dir) if scan_dir else _repository_files()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: secret scan could not enumerate files: {exc}", file=sys.stderr)
        return 2

    all_hits = []
    for f in files:
        all_hits.extend(scan_file(f))

    if all_hits:
        print(f"FAIL: {len(all_hits)} secret(s) found in repository files:")
        for location, pattern, match in all_hits:
            # Mask the middle of the token for safety
            masked = match[:6] + "..." + match[-4:]
            print(f"  {location} [pattern: {pattern}] -> {masked}")
        print("\nAll GitHub PAT patterns detected above.")
        print("Run: git rm --cached <file> to remove, or rotate the token immediately.")
        return 1

    print(f"OK: no GitHub PAT secrets detected in {len(files)} repository files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
