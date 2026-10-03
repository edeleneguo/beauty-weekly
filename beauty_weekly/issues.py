"""Issue registry and depth-safe navigation helpers."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = ROOT / "data" / "issues.json"
CATEGORIES = ("makeup", "fragrance")


def load_issues(path: Path = DEFAULT_REGISTRY, *, root: Path | None = None) -> list[dict]:
    path = Path(path)
    site_root = (root or path.parent.parent).resolve()
    issues = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(issues, list):
        raise ValueError("issue registry must be a list")
    seen: set[str] = set()
    previous_sort_key: str | None = None
    for issue in issues:
        issue_id = issue.get("id")
        if issue_id in seen:
            raise ValueError(f"duplicate issue id: {issue_id}")
        seen.add(issue_id)
        if issue.get("language") != "en":
            raise ValueError(f"public issue must be English: {issue_id}")
        sort_key = issue.get("sort_key", "")
        if previous_sort_key is not None and sort_key >= previous_sort_key:
            raise ValueError("issues must be ordered newest first")
        previous_sort_key = sort_key
        for category in CATEGORIES:
            target = site_root / issue.get(category, "")
            if not target.is_file():
                raise ValueError(f"missing {category} page for {issue_id}: {target}")
    return issues


def public_issues(path: Path = DEFAULT_REGISTRY) -> list[dict]:
    return load_issues(path)


def relative_issue_url(page: Path, target: Path) -> str:
    return Path(os.path.relpath(target.resolve(), page.resolve().parent)).as_posix()


def render_issue_options(
    page: Path, category: str, registry_path: Path = DEFAULT_REGISTRY
) -> str:
    if category not in CATEGORIES:
        raise ValueError(f"unsupported issue category: {category}")
    site_root = Path(registry_path).resolve().parent.parent
    options = ['<option value="">Past Issues</option>']
    for issue in load_issues(registry_path, root=site_root):
        value = relative_issue_url(page, site_root / issue[category])
        options.append(
            f'<option value="{html.escape(value, quote=True)}">'
            f'{html.escape(issue["label"])}</option>'
        )
    return "".join(options)
