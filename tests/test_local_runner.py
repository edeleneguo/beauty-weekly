import logging
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
