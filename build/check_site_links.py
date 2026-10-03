#!/usr/bin/env python3
"""Fail when a public HTML page points at a missing local target."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

SKIP_SCHEMES = {"http", "https", "mailto", "tel", "javascript", "data"}


def _local_target(root: Path, page: Path, raw_url: str) -> Path | None:
    value = raw_url.strip()
    if not value or value.startswith("#"):
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() in SKIP_SCHEMES or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    if path.startswith("/"):
        return root / path.lstrip("/")
    return page.parent / path


def collect_broken_links(
    root: Path, *, pages: list[Path] | None = None
) -> list[tuple[Path, str]]:
    root = root.resolve()
    candidates = pages or [
        *sorted(root.glob("*.html")),
        *sorted((root / "archive").rglob("*.html")),
    ]
    broken: list[tuple[Path, str]] = []
    for page in candidates:
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        refs = [tag.get("href", "") for tag in soup.find_all(href=True)]
        refs.extend(option.get("value", "") for option in soup.find_all("option", value=True))
        for raw_url in refs:
            target = _local_target(root, page.resolve(), raw_url)
            if target is not None and not target.resolve().exists():
                broken.append((page, raw_url))
    return broken


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args()
    broken = collect_broken_links(args.root)
    for page, target in broken:
        print(f"{page.relative_to(args.root.resolve())}: {target}")
    if broken:
        print(f"BROKEN_LINKS={len(broken)}")
        return 1
    print("BROKEN_LINKS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
