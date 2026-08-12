from pathlib import Path

import build.monthly_local_runner as runner


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
