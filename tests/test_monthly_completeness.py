# ruff: noqa: E501
"""Regression tests for historical monthly completeness restoration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(relative_path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_render_prefers_month_specific_shell(tmp_path, monkeypatch):
    render = _load("build/render.py", "render")
    month_dir = tmp_path / "data" / "months" / "2026-06" / "page_shells"
    month_dir.mkdir(parents=True)
    month_shell = month_dir / "index.html"
    month_shell.write_text("month shell", encoding="utf-8")
    monkeypatch.setattr(render, "ROOT", str(tmp_path))
    monkeypatch.setattr(render, "PAGE_SHELL_DIR", str(tmp_path / "templates" / "pages"))
    assert render._resolve_template_path("2026-06", "index.html") == str(month_shell)


def test_week27_radar_accepts_month_level_june_evidence():
    migration = _load("build/migrate_june_history.py", "migrate_june_history")
    candidate = {
        "section": "new_product_radar",
        "explicit_dates": [],
        "month_markers": ["2026-06"],
    }
    excluded = {
        "section": "new_product_radar",
        "explicit_dates": [],
        "month_markers": ["2026-05"],
    }
    heat = {
        "section": "heat_rankings",
        "explicit_dates": [],
        "month_markers": [],
    }

    assert migration._should_include_candidate("week-27", candidate) is True
    assert migration._should_include_candidate("week-27", excluded) is False
    assert migration._should_include_candidate("week-27", heat) is True


def test_monthly_audit_extracts_panel_counts():
    audit = _load("build/audit_monthly_completeness.py", "audit_monthly_completeness")
    html = """
    <h2 class="section-title">Makeup <em>Heat</em> Rankings <span class="sec-label">Section 03</span></h2>
    <h4><span>US</span><span>LUXURY</span></h4>
    <ul class="heat-accordion">
      <li class="heat-item"><div class="heat-item-header"></div></li>
      <li class="heat-item"><div class="heat-item-header"></div></li>
    </ul>
    <h4><span>CN</span><span>MASSTIGE</span></h4>
    <ul class="heat-accordion">
      <li class="heat-item"><div class="heat-item-header"></div></li>
    </ul>
    """
    counts = audit._extract_panel_counts(html)
    assert counts["US LUXURY"] == 2
    assert counts["CN MASSTIGE"] == 1
