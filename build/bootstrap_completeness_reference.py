#!/usr/bin/env python3
"""Create the immutable structural baseline for a newly generated month."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import month_data_dir, resolve_month  # noqa: E402


def main() -> int:
    month = resolve_month()
    month_dir = Path(month_data_dir(month))
    target = month_dir / "completeness_reference.json"
    if target.exists():
        print(f"Completeness reference already exists: {target}")
        return 0

    report = json.loads((month_dir / "report.json").read_text(encoding="utf-8"))
    products = report["products"]
    panels = ("US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE")
    canonical_counts = {
        topic: {
            section: {panel: len(products[topic][section][panel]) for panel in panels}
            for section in ("heat_rankings", "new_product_radar")
        }
        for topic in ("makeup", "fragrance")
    }
    reference = {
        "month": month,
        "baseline_type": "generated_month_pre_publish",
        "canonical_counts": canonical_counts,
        "render_shell_counts": {
            topic: {
                "news_cards": len(report.get("news", {}).get(topic, [])),
                "trend_cards": len(report.get("trends", {}).get(topic, [])),
            }
            for topic in ("makeup", "fragrance")
        },
    }
    target.write_text(
        json.dumps(reference, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Created completeness reference: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
