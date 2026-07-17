#!/usr/bin/env python3
"""Fail-closed validation for the single production render pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ("index.html", "index-cn.html", "fragrance.html", "fragrance-cn.html")


def validate_pipeline() -> list[str]:
    errors: list[str] = []
    renderer = (ROOT / "build" / "render.py").read_text(encoding="utf-8")
    for name in OUTPUTS:
        if not (ROOT / "templates" / "pages" / name).is_file():
            errors.append(f"missing authoritative page shell: templates/pages/{name}")
    if "PAGE_SHELL_DIR" not in renderer:
        errors.append("renderer does not declare the authoritative page-shell directory")
    if 'os.path.join(ROOT, template_name)' in renderer:
        errors.append("renderer still reads production outputs as templates")
    if "data/week28.json" in renderer and "legacy compatibility baseline only" not in renderer:
        errors.append("renderer appears to use legacy data as an authoritative input")
    for legacy_tool in ("extract_data.py", "fix_week28_data.py"):
        text = (ROOT / "build" / legacy_tool).read_text(encoding="utf-8")
        if "LEGACY ONE-TIME" not in text or "not a production pipeline entrypoint" not in text:
            errors.append(f"{legacy_tool} is not explicitly marked non-production")
    return errors


def main() -> int:
    errors = validate_pipeline()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Production pipeline structure ... OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
