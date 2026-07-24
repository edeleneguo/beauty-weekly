#!/usr/bin/env python3
"""Responsive full-width layout regression tests.

Verifies that the main content containers do NOT use a fixed max-width
(such as 1400px) that would create large blank margins on wide screens.
Content should fill the viewport width with only modest horizontal padding.

Run: python3 -m pytest tests/test_layout_responsive.py -v
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HTML_FILES = [
    "templates/pages/index.html",
    "templates/pages/fragrance.html",
    "index.html",
    "fragrance.html",
    "data/months/2026-06/page_shells/index.html",
    "data/months/2026-06/page_shells/fragrance.html",
]

SELECTORS_NEEDING_FULL_WIDTH = [
    ".section-shell",
    ".section-sep",
    ".appendix-section",
]


def _read_html(rel_path: str) -> str:
    full = os.path.join(ROOT, rel_path)
    if not os.path.exists(full):
        pytest.skip(f"File not found: {rel_path}")
    with open(full, encoding="utf-8") as f:
        return f.read()


def _extract_css_block(html: str) -> str:
    """Extract the content inside the first <style> tag."""
    m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    return m.group(1) if m else ""


def _has_fixed_max_width(css: str, selector: str) -> bool:
    """Check if a CSS rule for the given selector sets a fixed pixel max-width."""
    pattern = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.DOTALL)
    for match in pattern.finditer(css):
        body = match.group(1)
        if re.search(r"max-width\s*:\s*\d+px", body):
            return True
    return False


# ── Regression: no fixed max-width in any HTML file ──────────────────────


class TestNoFixedMaxWidth:
    """No HTML file should contain a fixed pixel max-width on layout containers."""

    @pytest.mark.parametrize("rel_path", HTML_FILES)
    def test_no_1400px_max_width(self, rel_path):
        """The string 'max-width: 1400px' must not appear in any HTML file."""
        html = _read_html(rel_path)
        assert "max-width: 1400px" not in html, (
            f"{rel_path} still contains 'max-width: 1400px' — full-width layout regression detected"
        )

    @pytest.mark.parametrize("rel_path", HTML_FILES)
    def test_no_fixed_pixel_max_width(self, rel_path):
        """No layout container should use a fixed pixel max-width value."""
        html = _read_html(rel_path)
        css = _extract_css_block(html)
        for selector in SELECTORS_NEEDING_FULL_WIDTH:
            assert not _has_fixed_max_width(css, selector), (
                f"{rel_path}: '{selector}' has a fixed pixel max-width — "
                "content should use full viewport width"
            )


# ── Positive: key selectors must exist and use auto margin ────────────────


class TestFullWidthLayoutPresent:
    """Key layout selectors must exist and use margin: 0 auto for centering."""

    @pytest.mark.parametrize("rel_path", HTML_FILES[:4])
    def test_selectors_have_auto_margin(self, rel_path):
        """section-shell, section-sep, appendix-section must use margin: * auto."""
        html = _read_html(rel_path)
        css = _extract_css_block(html)
        for selector in SELECTORS_NEEDING_FULL_WIDTH:
            pattern = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.DOTALL)
            match = pattern.search(css)
            assert match, f"{rel_path}: selector '{selector}' not found in CSS"
            body = match.group(1)
            assert re.search(r"margin\s*:\s*[^;]*auto", body), (
                f"{rel_path}: '{selector}' missing 'margin: ... auto' "
                "(needed for centered full-width layout)"
            )

    @pytest.mark.parametrize("rel_path", HTML_FILES[:4])
    def test_selectors_have_horizontal_padding(self, rel_path):
        """section-shell, appendix-section must have horizontal padding."""
        html = _read_html(rel_path)
        css = _extract_css_block(html)
        for selector in SELECTORS_NEEDING_FULL_WIDTH:
            pattern = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}", re.DOTALL)
            match = pattern.search(css)
            assert match, f"{rel_path}: selector '{selector}' not found in CSS"
            body = match.group(1)
            assert re.search(r"padding\s*:", body), (
                f"{rel_path}: '{selector}' missing padding declaration"
            )


# ── Tablet/mobile breakpoint preserved ────────────────────────────────────


class TestResponsiveBreakpoint:
    """The @media (max-width: 900px) breakpoint must remain for tablet/mobile."""

    @pytest.mark.parametrize("rel_path", HTML_FILES[:4])
    def test_mobile_breakpoint_exists(self, rel_path):
        """HTML must contain a max-width: 900px media query."""
        html = _read_html(rel_path)
        assert "@media" in html and "max-width: 900px" in html, (
            f"{rel_path}: missing @media (max-width: 900px) breakpoint"
        )
