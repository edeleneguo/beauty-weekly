#!/usr/bin/env python3
"""Tests for beauty_weekly.week dynamic week resolution.

Covers:
  1. current_iso_week deterministic output
  2. available_weeks listing
  3. resolve_week priority order (env > target > latest > current)
  4. _validate_week format enforcement
  5. weeks_dir / report_path helpers
"""

from datetime import date
from pathlib import Path

import pytest
from beauty_weekly.week import (
    _validate_week,
    available_weeks,
    current_iso_week,
    report_path,
    resolve_week,
    weeks_dir,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_WEEKS = ROOT / "data" / "weeks"


class TestCurrentIsoWeek:
    def test_known_date(self):
        assert current_iso_week(date(2026, 7, 21)) == "2026-W30"

    def test_jan_1(self):
        assert current_iso_week(date(2026, 1, 1)) == "2026-W01"

    def test_dec_31(self):
        assert current_iso_week(date(2025, 12, 31)) == "2026-W01"


class TestAvailableWeeks:
    def test_lists_report_json_dirs(self):
        weeks = available_weeks()
        assert isinstance(weeks, list)
        for w in weeks:
            assert (DATA_WEEKS / w / "report.json").exists()

    def test_sorted(self):
        weeks = available_weeks()
        assert weeks == sorted(weeks)


class TestValidateWeek:
    def test_valid(self):
        assert _validate_week("2026-W28") == "2026-W28"

    def test_valid_two_digit_week(self):
        assert _validate_week("2026-W05") == "2026-W05"

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid ISO week"):
            _validate_week("2026-W2")

    def test_invalid_no_dash(self):
        with pytest.raises(ValueError, match="Invalid ISO week"):
            _validate_week("2026W28")

    def test_invalid_letters(self):
        with pytest.raises(ValueError, match="Invalid ISO week"):
            _validate_week("2026-Wxx")


class TestResolveWeek:
    def test_explicit_target(self, monkeypatch):
        monkeypatch.delenv("BEAUTY_WEEKLY_WEEK", raising=False)
        assert resolve_week("2026-W15") == "2026-W15"

    def test_env_var_overrides_target(self, monkeypatch):
        monkeypatch.setenv("BEAUTY_WEEKLY_WEEK", "2025-W01")
        assert resolve_week("2026-W15") == "2025-W01"

    def test_falls_back_to_latest_available(self, monkeypatch):
        monkeypatch.delenv("BEAUTY_WEEKLY_WEEK", raising=False)
        result = resolve_week()
        available = available_weeks()
        if available:
            assert result == available[-1]

    def test_env_var_invalid_raises(self, monkeypatch):
        monkeypatch.setenv("BEAUTY_WEEKLY_WEEK", "bad")
        with pytest.raises(ValueError, match="Invalid ISO week"):
            resolve_week()


class TestHelpers:
    def test_weeks_dir(self):
        d = weeks_dir("2026-W28")
        assert d == DATA_WEEKS / "2026-W28"

    def test_report_path(self):
        p = report_path("2026-W28")
        assert p == DATA_WEEKS / "2026-W28" / "report.json"
