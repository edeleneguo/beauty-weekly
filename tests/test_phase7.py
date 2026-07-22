"""Tests for Phase 7: source evidence integrity and new-product qualification.

Covers:
  1. Evidence constant definitions
  2. EXPLICIT_EVIDENCE_ABSENCES structure
  3. Source-product referential integrity
  4. New-product qualification rules (historical and future)
  5. Evidence absence documentation
  6. Source evidence structure validation
  7. Combined evidence integrity validation
  8. Fail-closed behaviour: invalid references or silent New status fail
  9. Validate_evidence.py CLI script
 10. Protected files unchanged
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from beauty_weekly.evidence import (
    ABSENCE_GAP_TYPES,
    EVIDENCE_TYPES,
    EXPLICIT_EVIDENCE_ABSENCES,
    PHASE,
    QUARANTINE_STATUSES,
    SOURCES_SCHEMA_VERSION,
    validate_evidence_absences,
    validate_evidence_integrity,
    validate_new_product_qualification,
    validate_source_evidence_structure,
    validate_source_product_referential_integrity,
)

ROOT = Path(__file__).resolve().parent.parent
WEEKS_DIR = ROOT / "data" / "weeks" / "2026-W28"
HTML_FILES = ("index.html", "index-cn.html", "fragrance.html", "fragrance-cn.html")


@pytest.fixture(scope="session")
def report_data():
    return json.loads((WEEKS_DIR / "report.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sources_data():
    return json.loads((WEEKS_DIR / "sources.json").read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Evidence constant definitions
# ══════════════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_phase_is_7(self):
        assert PHASE == 7

    def test_sources_schema_version(self):
        assert SOURCES_SCHEMA_VERSION == "2.0.0"

    def test_evidence_types_include_product_page(self):
        assert "product_page" in EVIDENCE_TYPES

    def test_evidence_types_frozen(self):
        assert isinstance(EVIDENCE_TYPES, frozenset)

    def test_quarantine_statuses_frozen(self):
        assert isinstance(QUARANTINE_STATUSES, frozenset)

    def test_quarantine_statuses_core_values(self):
        assert "verified" in QUARANTINE_STATUSES
        assert "unverified" in QUARANTINE_STATUSES
        assert "out-of-window" in QUARANTINE_STATUSES

    def test_absence_gap_types_frozen(self):
        assert isinstance(ABSENCE_GAP_TYPES, frozenset)

    def test_absence_gap_types_include_no_url(self):
        assert "no_url" in ABSENCE_GAP_TYPES


# ══════════════════════════════════════════════════════════════════════════════
# 2. EXPLICIT_EVIDENCE_ABSENCES structure
# ══════════════════════════════════════════════════════════════════════════════


class TestExplicitAbsences:
    def test_two_known_absences(self):
        assert len(EXPLICIT_EVIDENCE_ABSENCES) == 2

    def test_kunlun_snow_present(self):
        names = {a["product_name"] for a in EXPLICIT_EVIDENCE_ABSENCES}
        assert "To Summer Kunlun Snow" in names

    def test_boiled_water_present(self):
        names = {a["product_name"] for a in EXPLICIT_EVIDENCE_ABSENCES}
        assert "Scent Library Boiled Water" in names

    def test_all_absences_have_required_fields(self):
        required = {"product_name", "panel", "section", "topic", "gap_type", "reason"}
        for a in EXPLICIT_EVIDENCE_ABSENCES:
            for field in required:
                assert field in a, f"Missing '{field}' in absence record"

    def test_all_gap_types_valid(self):
        for a in EXPLICIT_EVIDENCE_ABSENCES:
            assert a["gap_type"] in ABSENCE_GAP_TYPES

    def test_no_invented_urls(self):
        for a in EXPLICIT_EVIDENCE_ABSENCES:
            assert "url" not in a
            assert "source" not in a


# ══════════════════════════════════════════════════════════════════════════════
# 3. Source-product referential integrity
# ══════════════════════════════════════════════════════════════════════════════


class TestReferentialIntegrity:
    def test_real_data_passes(self, report_data, sources_data):
        errors = validate_source_product_referential_integrity(report_data, sources_data)
        assert errors == [], f"Referential integrity errors: {errors}"

    def test_missing_source_detected(self, sources_data):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Test Product",
                                "detail": {
                                    "price_link": {"link": "https://nonexistent.example.com/fake"}
                                },
                            }
                        ]
                    }
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_source_product_referential_integrity(report, sources_data)
        assert len(errors) >= 1
        assert "nonexistent.example.com" in errors[0]

    def test_empty_link_ok(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "No Link Product",
                                "detail": {"price_link": {"link": ""}},
                            }
                        ]
                    }
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        sources = {"sources": []}
        errors = validate_source_product_referential_integrity(report, sources)
        assert errors == []

    def test_orphaned_source_detected(self, report_data):
        sources = {
            "sources": [
                {
                    "id": "orph",
                    "url": "https://orphan.example.com",
                    "type": "product_page",
                }
            ]
        }
        errors = validate_source_product_referential_integrity(report_data, sources)
        assert any("not referenced" in e.lower() for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 4. New-product qualification rules
# ══════════════════════════════════════════════════════════════════════════════


class TestNewProductQualification:
    def test_real_data_passes_historical(self, report_data):
        errors = validate_new_product_qualification(report_data, is_historical=True)
        assert errors == [], f"Qualification errors: {errors}"

    def test_non_historical_no_evidence_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "New Product No Evidence",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert len(errors) >= 1
        assert "no launch_evidence" in errors[0]

    def test_non_historical_unverified_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Unverified New",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "quarantine_status": "unverified",
                                    "launch_date": "2026-06-01",
                                    "quarantine_reason": "no official announcement",
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert any("not 'verified'" in e for e in errors)

    def test_non_historical_verified_with_evidence_passes(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Verified New",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "quarantine_status": "verified",
                                    "launch_date": "2026-06-01",
                                    "evidence": {
                                        "url": "https://brand.com/launch",
                                        "type": "launch_announcement",
                                    },
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert errors == []

    def test_invalid_quarantine_status_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Bad Status",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "quarantine_status": "pending",
                                    "launch_date": "2026-06-01",
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert any("invalid quarantine_status" in e for e in errors)

    def test_missing_launch_date_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "No Launch Date",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "quarantine_status": "verified",
                                    "launch_date": "",
                                    "evidence": {"url": "https://x.com/p"},
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert any("missing launch_date" in e for e in errors)

    def test_unverified_without_reason_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "No Reason",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "quarantine_status": "unverified",
                                    "launch_date": "2026-06-01",
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=True)
        assert any("requires quarantine_reason" in e for e in errors)

    def test_verified_without_evidence_or_absence_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Verified No Evidence",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "quarantine_status": "verified",
                                    "launch_date": "2026-06-01",
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=True)
        assert any("no evidence and no absence_markers" in e for e in errors)

    def test_missing_quarantine_status_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Missing QS",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                                "launch_evidence": {
                                    "launch_date": "2026-06-01",
                                },
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=True)
        assert any("missing quarantine_status" in e for e in errors)

    def test_non_new_badge_products_not_checked(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Regular Product",
                                "detail": {"price_link": {"link": "https://x.com"}},
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# 5. Evidence absence documentation
# ══════════════════════════════════════════════════════════════════════════════


class TestEvidenceAbsences:
    def test_real_data_passes(self, report_data, sources_data):
        errors = validate_evidence_absences(report_data, sources_data)
        assert errors == [], f"Absence errors: {errors}"

    def test_missing_absence_detected(self, report_data):
        sources = {"provenance": {"evidence_absences": []}}
        errors = validate_evidence_absences(report_data, sources)
        assert len(errors) >= 2
        assert any("Kunlun" in e for e in errors)
        assert any("Boiled Water" in e for e in errors)

    def test_malformed_absence_record(self, report_data):
        sources = {
            "provenance": {
                "evidence_absences": [{"product_name": "", "gap_type": "bad", "reason": ""}]
            }
        }
        errors = validate_evidence_absences(report_data, sources)
        assert len(errors) >= 1

    def test_invalid_gap_type_detected(self, report_data):
        sources = {
            "provenance": {
                "evidence_absences": [
                    {
                        "product_name": "Test",
                        "gap_type": "nonexistent_type",
                        "reason": "test reason",
                    }
                ]
            }
        }
        errors = validate_evidence_absences(report_data, sources)
        assert any("invalid gap_type" in e for e in errors)

    def test_no_provenance_block_fails(self, report_data):
        sources = {}
        errors = validate_evidence_absences(report_data, sources)
        assert len(errors) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 6. Source evidence structure validation
# ══════════════════════════════════════════════════════════════════════════════


class TestSourceEvidenceStructure:
    def test_real_data_passes(self, sources_data):
        errors = validate_source_evidence_structure(sources_data)
        assert errors == [], f"Structure errors: {errors}"

    def test_missing_provenance_fails(self):
        errors = validate_source_evidence_structure({"sources": []})
        assert any("missing provenance" in e for e in errors)

    def test_missing_migration_recorded_at_in_provenance(self):
        sources = {
            "provenance": {"phase": 7},
            "sources": [],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("migration_recorded_at" in e for e in errors)

    def test_wrong_phase_fails(self):
        sources = {
            "provenance": {"migration_recorded_at": "2026-07-17T00:00:00Z", "phase": 6},
            "sources": [],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("phase" in e for e in errors)

    def test_source_missing_checked_at_fails(self):
        sources = {
            "provenance": {"migration_recorded_at": "2026-07-17T00:00:00Z", "phase": 7},
            "sources": [
                {
                    "id": "s1",
                    "type": "product_page",
                    "url": "https://x.com",
                    "provenance": {"verification_status": "verified"},
                }
            ],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("s1" in e and "checked_at" in e for e in errors)

    def test_source_bad_checked_at_format_fails(self):
        sources = {
            "provenance": {"migration_recorded_at": "2026-07-17T00:00:00Z", "phase": 7},
            "sources": [
                {
                    "id": "s1",
                    "type": "product_page",
                    "url": "https://x.com",
                    "checked_at": "not-a-date",
                }
            ],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("not valid ISO-8601" in e for e in errors)

    def test_source_unknown_type_fails(self):
        sources = {
            "provenance": {"migration_recorded_at": "2026-07-17T00:00:00Z", "phase": 7},
            "sources": [
                {
                    "id": "s1",
                    "type": "bogus_type",
                    "url": "https://x.com",
                    "checked_at": "2026-07-17T00:00:00Z",
                }
            ],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("unknown type" in e for e in errors)

    def test_source_missing_provenance_fails(self):
        sources = {
            "provenance": {"migration_recorded_at": "2026-07-17T00:00:00Z", "phase": 7},
            "sources": [
                {
                    "id": "s1",
                    "type": "product_page",
                    "url": "https://x.com",
                    "checked_at": "2026-07-17T00:00:00Z",
                }
            ],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("s1" in e and "missing provenance" in e for e in errors)

    def test_source_missing_verification_status_fails(self):
        sources = {
            "provenance": {"migration_recorded_at": "2026-07-17T00:00:00Z", "phase": 7},
            "sources": [
                {
                    "id": "s1",
                    "type": "product_page",
                    "url": "https://x.com",
                    "checked_at": "2026-07-17T00:00:00Z",
                    "provenance": {},
                }
            ],
        }
        errors = validate_source_evidence_structure(sources)
        assert any("verification_status" in e for e in errors)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Combined evidence integrity validation
# ══════════════════════════════════════════════════════════════════════════════


class TestCombinedValidation:
    def test_real_data_passes(self, report_data, sources_data):
        errors = validate_evidence_integrity(report_data, sources_data, is_historical=True)
        assert errors == [], f"Combined validation errors: {errors}"

    def test_fail_closed_on_any_error(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "Bad",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": "https://x.com"}},
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        sources = {
            "provenance": {
                "checked_at": "2026-07-17T00:00:00Z",
                "phase": 7,
                "evidence_absences": [],
            },
            "sources": [
                {
                    "id": "s1",
                    "type": "product_page",
                    "url": "https://x.com",
                    "checked_at": "2026-07-17T00:00:00Z",
                    "provenance": {"verification_status": "verified"},
                }
            ],
        }
        errors = validate_evidence_integrity(report, sources, is_historical=False)
        assert len(errors) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 8. Fail-closed: invalid references and silent New status
# ══════════════════════════════════════════════════════════════════════════════


class TestFailClosed:
    def test_silent_new_status_rejected(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {},
                    "new_product_radar": {
                        "US LUXURY": [
                            {
                                "name": "Ghost New",
                                "new_badge": "New",
                                "detail": {"price_link": {"link": ""}},
                            }
                        ],
                    },
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        errors = validate_new_product_qualification(report, is_historical=False)
        assert len(errors) >= 1

    def test_invalid_source_url_fails(self):
        report = {
            "products": {
                "makeup": {
                    "heat_rankings": {
                        "US LUXURY": [
                            {
                                "name": "X",
                                "detail": {"price_link": {"link": "https://missing.example.com"}},
                            }
                        ]
                    },
                    "new_product_radar": {},
                },
                "fragrance": {"heat_rankings": {}, "new_product_radar": {}},
            }
        }
        sources = {"sources": []}
        errors = validate_source_product_referential_integrity(report, sources)
        assert len(errors) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 9. Validate_evidence.py CLI script
# ══════════════════════════════════════════════════════════════════════════════


class TestValidateEvidenceScript:
    def test_script_exits_zero(self):
        env = os.environ.copy()
        env["BEAUTY_WEEKLY_WEEK"] = "2026-W28"
        result = subprocess.run(
            [sys.executable, str(ROOT / "build" / "validate_evidence.py")],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=env,
        )
        assert result.returncode == 0, f"Script failed:\n{result.stdout}\n{result.stderr}"
        assert "OK" in result.stdout


# ══════════════════════════════════════════════════════════════════════════════
# 10. Protected files unchanged
# ══════════════════════════════════════════════════════════════════════════════


class TestProtectedFiles:
    def test_week28_json_unchanged(self):
        p = ROOT / "data" / "week28.json"
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        assert h == "db31d10d682ace6f4ae43183816d2c31913b4da09c5030db1fedfaf6f1221ac8"

    def test_html_files_exist(self):
        for name in HTML_FILES:
            assert (ROOT / name).exists(), f"Missing: {name}"
