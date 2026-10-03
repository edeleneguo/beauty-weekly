#!/usr/bin/env python3
"""Render one depth-safe English issue menu into every published page."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.issues import render_issue_options  # noqa: E402

SELECT_RE = re.compile(
    r'<select\b[^>]*class="(?:issue-select|week-select)"[^>]*>.*?</select>',
    re.DOTALL,
)
BANNER_RIGHT_RE = re.compile(
    r'<div class="banner-right">(?P<body>.*?)</div>\s*</header>', re.DOTALL
)
ANCHOR_RE = re.compile(r'<a\b[^>]*>.*?</a>', re.DOTALL)
LEGACY_SELECTOR_RE = re.compile(
    r'<div class="week-selector"[^>]*>.*?<div class="week-dropdown">.*?</div>\s*</div>',
    re.DOTALL,
)
LANG_SWITCH_RE = re.compile(r'<div class="lang-switch-bar">.*?</div>', re.DOTALL)
BROKEN_OGEE_LINK = (
    '<a href=iv class="heat-detail-value">'
    'NSF Certified Organic · 多用途 · 6/22 Sephora上市'
)
FIXED_OGEE_LINK = (
    '<a href="https://ogee.com/products/sculpted-complexion-stick" '
    'target="_blank" class="heat-link-icon" title="View product">🔗</a>'
    '</div></div><div class="heat-detail-cell">'
    '<div class="heat-detail-label">核心卖点</div>'
    '<div class="heat-detail-value">NSF Certified Organic · 多用途 · 6/22 Sephora上市'
)


def _normalize_navigation_eol(value: str) -> str:
    """Avoid CR-at-EOL warnings only around rewritten legacy blocks."""
    lines = value.splitlines(keepends=True)
    marked = {
        index
        for index, line in enumerate(lines)
        if any(
            marker in line
            for marker in ("issue-select", "lang-switch-bar", "banner-right", "ogee.com/products")
        )
    }
    for index in {
        nearby
        for marked_index in marked
        for nearby in range(max(0, marked_index - 3), min(len(lines), marked_index + 4))
    }:
        if lines[index].endswith("\r\n"):
            lines[index] = lines[index][:-2] + "\n"
    return "".join(lines)


def _category(page: Path) -> str:
    return "fragrance" if page.name.startswith("fragrance") else "makeup"


def _relative(page: Path, target: Path) -> str:
    return Path(os.path.relpath(target.resolve(), page.resolve().parent)).as_posix()


def update_navigation_text(page: Path, source: str, *, root: Path = ROOT) -> str:
    category = _category(page)
    options = render_issue_options(page, category, root / "data" / "issues.json")
    select = (
        '<select class="issue-select" aria-label="Past issues selector" '
        'onchange="if(this.value) window.location.href=this.value">'
        f"{options}</select>"
    )
    source = source.replace(BROKEN_OGEE_LINK, FIXED_OGEE_LINK)
    normalized, _legacy_count = LEGACY_SELECTOR_RE.subn(
        f'<div class="week-selector">{select}</div>', source, count=1
    )
    updated, count = SELECT_RE.subn(select, normalized, count=1)

    other = "fragrance" if category == "makeup" else "makeup"
    target_name = "fragrance.html" if other == "fragrance" else "index.html"
    label = "Fragrance" if other == "fragrance" else "Makeup"
    category_link = (
        f'<a href="{_relative(page, root / target_name)}" class="glass-pill">'
        f"{label}</a>"
    )

    def replace_banner(match: re.Match[str]) -> str:
        body = ANCHOR_RE.sub("", match.group("body"))
        return f'<div class="banner-right">{body}{category_link}</div></header>'

    updated, banner_count = BANNER_RIGHT_RE.subn(replace_banner, updated, count=1)
    if count == 1 and banner_count == 1:
        return _normalize_navigation_eol(updated)

    if count != 1:
        raise ValueError(f"unsupported navigation shell in {page}")
    new_switch_bar = (
        '<div class="lang-switch-bar">'
        f'{category_link.replace("glass-pill", "section-jump-btn")}'
        "</div>"
    )
    updated, switch_count = LANG_SWITCH_RE.subn(new_switch_bar, updated, count=1)
    if switch_count != 1:
        raise ValueError(f"expected one language switch bar in {page}")
    return _normalize_navigation_eol(updated)


def published_pages(root: Path = ROOT) -> list[Path]:
    return [
        root / "index.html",
        root / "fragrance.html",
        *sorted((root / "archive").rglob("*.html")),
    ]


def update_all(*, root: Path = ROOT, check: bool = False) -> list[Path]:
    changed: list[Path] = []
    for page in published_pages(root):
        source = page.read_bytes().decode("utf-8")
        updated = update_navigation_text(page, source, root=root)
        if source == updated:
            continue
        changed.append(page)
        if not check:
            page.write_bytes(updated.encode("utf-8"))
    for name in ("index.html", "fragrance.html"):
        template = root / "templates" / "pages" / name
        if not template.is_file():
            continue
        source = template.read_bytes().decode("utf-8")
        updated = update_navigation_text(root / name, source, root=root)
        if source == updated:
            continue
        changed.append(template)
        if not check:
            template.write_bytes(updated.encode("utf-8"))
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    changed = update_all(root=args.root.resolve(), check=args.check)
    if args.check and changed:
        for page in changed:
            print(f"navigation drift: {page.relative_to(args.root.resolve())}")
        return 1
    print(f"updated navigation in {len(changed)} page(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
