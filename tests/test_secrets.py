#!/usr/bin/env python3
"""Tests for build/check_secrets.py secret scanner.

Verifies that the scanner correctly detects GitHub PAT patterns and
returns clean for files without secrets.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "build"))
from check_secrets import scan_file


class TestScanFile:
    """Unit tests for scan_file()."""

    def test_clean_file_no_hits(self, tmp_path):
        fp = tmp_path / "clean.txt"
        fp.write_text("no secrets here\njust normal content\n")
        hits = scan_file(str(fp))
        assert hits == []

    def test_detects_ghp_pat(self, tmp_path):
        fp = tmp_path / "leaked.txt"
        token = "ghp_" + "A" * 40
        fp.write_text(f'token = "{token}"\n')
        hits = scan_file(str(fp))
        assert len(hits) >= 1
        assert any("ghp_" in h[2] for h in hits)

    def test_detects_gho_pat(self, tmp_path):
        fp = tmp_path / "oauth.txt"
        token = "gho_" + "B" * 40
        fp.write_text(f"GITHUB_TOKEN: {token}\n")
        hits = scan_file(str(fp))
        assert len(hits) >= 1
        assert any("gho_" in h[2] for h in hits)

    def test_detects_github_pat_finegrained(self, tmp_path):
        fp = tmp_path / "fine.txt"
        text = "github_pat_" + "A" * 82 + "\n"
        fp.write_text(text)
        hits = scan_file(str(fp))
        assert len(hits) >= 1
        assert any("github_pat_" in h[2] for h in hits)

    def test_detects_in_json(self, tmp_path):
        fp = tmp_path / "config.json"
        token = "ghp_" + "C" * 40
        fp.write_text(f'{{"api_key": "{token}"}}\n')
        hits = scan_file(str(fp))
        assert len(hits) >= 1

    def test_short_ghp_not_flagged(self, tmp_path):
        fp = tmp_path / "short.txt"
        fp.write_text("ghp_tooshort\n")
        hits = scan_file(str(fp))
        assert hits == []

    def test_binary_file_handled(self, tmp_path):
        fp = tmp_path / "binary.bin"
        fp.write_bytes(b"\x00\x01\x02\x03" * 100)
        hits = scan_file(str(fp))
        assert hits == []


class TestScanTrackedFiles:
    """Integration test: run the full scan on the actual repository."""

    def test_no_secrets_in_repo(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "build", "check_secrets.py")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"check_secrets.py failed with exit {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "FAIL" not in result.stdout
