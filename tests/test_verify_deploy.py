#!/usr/bin/env python3
"""Tests for build/verify_deploy.sh deploy verification behavior.

Uses a local HTTP server to test hash comparison, retry logic,
manifest verification, ISO week checking, and failure reporting
without touching the real deployment.
"""

import hashlib
import http.server
import json
import os
import subprocess
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_SCRIPT = os.path.join(ROOT, "build", "verify_deploy.sh")

FILES = ("index.html", "fragrance.html")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress server logs during tests


def _start_server(directory: str, port: int) -> http.server.HTTPServer:
    handler = lambda *a, **kw: _QuietHandler(*a, directory=directory, **kw)
    srv = http.server.HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


class TestVerifyDeployMatch:
    """When remote matches local, script exits 0."""

    def test_all_match(self, tmp_path):
        for fn in FILES:
            content = f"<html>{fn} content</html>".encode()
            (tmp_path / fn).write_bytes(content)

        srv = _start_server(str(tmp_path), 18920)
        try:
            result = subprocess.run(
                [VERIFY_SCRIPT, "http://127.0.0.1:18920"],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "RESULT: PASS" in result.stdout
            assert "PASS: 2" in result.stdout
        finally:
            srv.shutdown()


class TestVerifyDeployMismatch:
    """When remote differs from local, script exits 1."""

    def test_mismatch_detected(self, tmp_path):
        for fn in FILES:
            (tmp_path / fn).write_bytes(f"<html>{fn} local</html>".encode())
        # Serve different content
        srv_dir = tmp_path / "remote"
        srv_dir.mkdir()
        for fn in FILES:
            (srv_dir / fn).write_bytes(f"<html>{fn} REMOTE DIFFERENT</html>".encode())

        srv = _start_server(str(srv_dir), 18921)
        try:
            result = subprocess.run(
                [VERIFY_SCRIPT, "http://127.0.0.1:18921"],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 1, result.stdout + result.stderr
            assert "RESULT: FAIL" in result.stdout
            assert "MISMATCH" in result.stdout
        finally:
            srv.shutdown()


class TestVerifyDeployMissingLocal:
    """When a local file is missing, script reports error and exits 1."""

    def test_missing_local_file(self, tmp_path):
        # Only create some files
        (tmp_path / "index.html").write_bytes(b"<html>only one</html>")
        # fragrance.html is missing

        srv = _start_server(str(tmp_path), 18922)
        try:
            result = subprocess.run(
                [VERIFY_SCRIPT, "http://127.0.0.1:18922"],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 1
            assert "missing locally" in result.stdout
            assert "RESULT: FAIL" in result.stdout
        finally:
            srv.shutdown()


class TestVerifyDeployRetry:
    """Script retries on transient failures."""

    def test_server_down_triggers_retries(self, tmp_path):
        for fn in FILES:
            (tmp_path / fn).write_bytes(f"<html>{fn}</html>".encode())

        # No server started - curl will fail, retries should exhaust
        result = subprocess.run(
            [VERIFY_SCRIPT, "http://127.0.0.1:19999"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,  # allow time for retries
        )
        assert result.returncode == 1
        assert "DOWNLOAD FAILED" in result.stdout
        assert "RESULT: FAIL" in result.stdout


class TestVerifyDeployManifest:
    """Script verifies SHA256 hashes against a manifest file."""

    def test_manifest_match(self, tmp_path):
        content_map = {}
        size_map = {}
        for fn in FILES:
            content = f"<html>{fn} manifest content</html>".encode()
            (tmp_path / fn).write_bytes(content)
            content_map[fn] = _sha256(content)
            size_map[fn] = len(content)

        manifest = {
            "week": "2026-W30",
            "artifacts": {fn: {"sha256": h, "size": size_map[fn]} for fn, h in content_map.items()},
        }
        manifest_path = tmp_path / "deploy-manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        srv = _start_server(str(tmp_path), 18923)
        try:
            result = subprocess.run(
                [
                    VERIFY_SCRIPT,
                    "http://127.0.0.1:18923",
                    "--manifest",
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "RESULT: PASS" in result.stdout
            assert "MANIFEST OK" in result.stdout
        finally:
            srv.shutdown()

    def test_manifest_mismatch(self, tmp_path):
        for fn in FILES:
            (tmp_path / fn).write_bytes(f"<html>{fn} local</html>".encode())

        # Serve different content so remote hash differs from manifest
        srv_dir = tmp_path / "remote"
        srv_dir.mkdir()
        for fn in FILES:
            (srv_dir / fn).write_bytes(f"<html>{fn} REMOTE</html>".encode())

        # Manifest says local hashes are correct, but remote is different
        content_map = {}
        size_map = {}
        for fn in FILES:
            raw = (tmp_path / fn).read_bytes()
            content_map[fn] = _sha256(raw)
            size_map[fn] = len(raw)

        manifest = {
            "week": "2026-W30",
            "artifacts": {fn: {"sha256": h, "size": size_map[fn]} for fn, h in content_map.items()},
        }
        manifest_path = tmp_path / "deploy-manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        srv = _start_server(str(srv_dir), 18924)
        try:
            result = subprocess.run(
                [
                    VERIFY_SCRIPT,
                    "http://127.0.0.1:18924",
                    "--manifest",
                    str(manifest_path),
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 1
            assert "MANIFEST MISMATCH" in result.stdout
            assert "RESULT: FAIL" in result.stdout
        finally:
            srv.shutdown()


class TestVerifyDeployWeek:
    """Script verifies ISO week number is present in remote content."""

    def test_week_found(self, tmp_path):
        for fn in FILES:
            content = f"<html><h1>Week 30</h1>{fn} content</html>".encode()
            (tmp_path / fn).write_bytes(content)

        srv = _start_server(str(tmp_path), 18925)
        try:
            result = subprocess.run(
                [
                    VERIFY_SCRIPT,
                    "http://127.0.0.1:18925",
                    "--week",
                    "2026-W30",
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "WEEK OK" in result.stdout
            assert "RESULT: PASS" in result.stdout
        finally:
            srv.shutdown()

    def test_week_not_found(self, tmp_path):
        for fn in FILES:
            # Content has Week 25 instead of expected Week 30
            content = f"<html><h1>Week 25</h1>{fn} content</html>".encode()
            (tmp_path / fn).write_bytes(content)

        srv = _start_server(str(tmp_path), 18926)
        try:
            result = subprocess.run(
                [
                    VERIFY_SCRIPT,
                    "http://127.0.0.1:18926",
                    "--week",
                    "2026-W30",
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 1
            assert "expected Week 30 in content but not found" in result.stdout
            assert "RESULT: FAIL" in result.stdout
        finally:
            srv.shutdown()


class TestVerifyDeployManifestAndWeek:
    """Script combines manifest and week verification."""

    def test_manifest_and_week_match(self, tmp_path):
        content_map = {}
        size_map = {}
        for fn in FILES:
            content = f"<html><h1>Week 30</h1>{fn} content</html>".encode()
            (tmp_path / fn).write_bytes(content)
            content_map[fn] = _sha256(content)
            size_map[fn] = len(content)

        manifest = {
            "week": "2026-W30",
            "artifacts": {fn: {"sha256": h, "size": size_map[fn]} for fn, h in content_map.items()},
        }
        manifest_path = tmp_path / "deploy-manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        srv = _start_server(str(tmp_path), 18927)
        try:
            result = subprocess.run(
                [
                    VERIFY_SCRIPT,
                    "http://127.0.0.1:18927",
                    "--manifest",
                    str(manifest_path),
                    "--week",
                    "2026-W30",
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert "MANIFEST OK" in result.stdout
            assert "WEEK OK" in result.stdout
            assert "RESULT: PASS" in result.stdout
        finally:
            srv.shutdown()

    def test_manifest_ok_but_week_wrong(self, tmp_path):
        content_map = {}
        size_map = {}
        for fn in FILES:
            # Content has wrong week
            content = f"<html><h1>Week 25</h1>{fn} content</html>".encode()
            (tmp_path / fn).write_bytes(content)
            content_map[fn] = _sha256(content)
            size_map[fn] = len(content)

        manifest = {
            "week": "2026-W30",
            "artifacts": {fn: {"sha256": h, "size": size_map[fn]} for fn, h in content_map.items()},
        }
        manifest_path = tmp_path / "deploy-manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        srv = _start_server(str(tmp_path), 18928)
        try:
            result = subprocess.run(
                [
                    VERIFY_SCRIPT,
                    "http://127.0.0.1:18928",
                    "--manifest",
                    str(manifest_path),
                    "--week",
                    "2026-W30",
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                timeout=15,
            )
            assert result.returncode == 1
            assert "MANIFEST OK" in result.stdout
            assert "expected Week 30 in content but not found" in result.stdout
            assert "RESULT: FAIL" in result.stdout
        finally:
            srv.shutdown()
