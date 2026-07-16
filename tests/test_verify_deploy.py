#!/usr/bin/env python3
"""Tests for build/verify_deploy.sh deploy verification behavior.

Uses a local HTTP server to test hash comparison, retry logic,
and failure reporting without touching the real deployment.
"""

import hashlib
import http.server
import os
import subprocess
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_SCRIPT = os.path.join(ROOT, "build", "verify_deploy.sh")

FILES = ("index.html", "index-cn.html", "fragrance.html", "fragrance-cn.html")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
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
            assert "FAIL: 0" in result.stdout or "FAIL: 0" in result.stdout
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
        (tmp_path / "index-cn.html").write_bytes(b"<html>only two</html>")
        # fragrance.html and fragrance-cn.html are missing

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

        # No server started – curl will fail, retries should exhaust
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
