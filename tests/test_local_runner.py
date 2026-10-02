import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import build.monthly_local_runner as runner
import pytest


def test_clean_env_strips_all_auth_overrides(monkeypatch):
    for name in runner.STRIP_ENV:
        monkeypatch.setenv(name, "secret")
    env = runner.clean_env({"BEAUTY_MONTHLY_MONTH": "2026-07"})
    assert all(name not in env for name in runner.STRIP_ENV)
    assert env["BEAUTY_MONTHLY_MONTH"] == "2026-07"


def test_valid_month():
    assert runner.valid_month("2026-07") == "2026-07"


def test_launchagent_never_contains_credentials():
    plist = Path(__file__).parents[1] / "ops" / "com.edelene.beauty-weekly-monthly.plist"
    text = plist.read_text()
    assert "sk-" not in text
    assert "auth.json" not in text


def test_restore_keeps_failed_canonical_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    month_dir = tmp_path / "data" / "months" / "2026-07"
    month_dir.mkdir(parents=True)
    (month_dir / "report.json").write_text("candidate")
    (tmp_path / "index.html").write_text("failed-public")
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "index.html").write_text("published")

    runner.restore("2026-07", backup)

    assert (month_dir / "report.json").read_text() == "candidate"
    assert (tmp_path / "index.html").read_text() == "published"


def test_codex_login_preflight_passes_on_first_attempt(monkeypatch):
    monkeypatch.setattr(runner, "codex_logged_in", lambda: True)
    runner._codex_login_preflight()


def test_codex_login_preflight_passes_on_retry(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    sleeps = []
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)
    with patch.object(runner, "codex_logged_in", side_effect=[False, True]):
        runner._codex_login_preflight(delay_seconds=2)
    assert "passed on attempt 2" in caplog.text
    assert sleeps == [2]


def test_codex_login_preflight_raises_after_exhausted_attempts(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    sleeps = []
    monkeypatch.setattr(runner.time, "sleep", sleeps.append)
    with (
        patch.object(runner, "codex_logged_in", side_effect=[False, False, False]),
        pytest.raises(RuntimeError, match=r"3 preflight attempt\(s\)"),
    ):
        runner._codex_login_preflight(max_attempts=3, delay_seconds=2)
    assert "failed after 3 attempts" in caplog.text
    assert sleeps == [2, 2]


def test_codex_login_preflight_uses_default_max_attempts(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    with (
        patch.object(runner, "codex_logged_in", side_effect=[False, False, False]),
        pytest.raises(RuntimeError, match=r"3 preflight attempt\(s\)"),
    ):
        runner._codex_login_preflight()
    assert "failed after 3 attempts" in caplog.text


def test_already_published_reads_deploy_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "deploy-manifest.json").write_text(
        json.dumps({"month": "2026-09"}), encoding="utf-8"
    )

    assert runner.already_published("2026-09") is True
    assert runner.already_published("2026-08") is False


def test_clean_checkout_allows_only_reused_target_raw(monkeypatch):
    dirty = subprocess.CompletedProcess(
        [], 0, stdout="?? data/months/2026-09/raw_collected.json\n", stderr=""
    )
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: dirty)

    runner.ensure_clean_checkout("2026-09", allow_target_raw=True)
    with pytest.raises(RuntimeError, match="dirty automation checkout"):
        runner.ensure_clean_checkout("2026-09", allow_target_raw=False)


def test_write_status_is_machine_readable(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "STATE_DIR", tmp_path)

    runner.write_status("2026-09", "failed", detail="generation failed")

    status = json.loads((tmp_path / "monthly-status.json").read_text(encoding="utf-8"))
    assert status["month"] == "2026-09"
    assert status["state"] == "failed"
    assert status["detail"] == "generation failed"
    assert status["updated_at"].endswith("Z")


def test_launchagent_uses_dedicated_venv_and_recovery_schedule():
    plist = Path(__file__).parents[1] / "ops" / "com.edelene.beauty-weekly-monthly.plist"
    text = plist.read_text(encoding="utf-8")

    assert "/.openclaw/automation/beauty-weekly/.venv/bin/python" in text
    assert text.count("<key>Day</key><integer>1</integer>") >= 2
    assert "<key>Day</key><integer>2</integer>" in text
    assert "<key>CODEX_MODEL</key><string>gpt-5.6-sol</string>" in text
