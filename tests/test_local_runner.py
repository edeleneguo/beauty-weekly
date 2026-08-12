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
