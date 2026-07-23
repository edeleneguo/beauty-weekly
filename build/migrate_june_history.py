#!/usr/bin/env python3
"""Recover June 2026 English historical candidates from the archive snapshot.

This script reads only the required archive pages from commit ``709c63b``:

* ``archive/week-23/{index,fragrance}.html``
* ``archive/week-25/{index,fragrance}.html``
* ``archive/week-26/{index,fragrance}.html``
* ``archive/week-27/{index,fragrance}.html``

It extracts English-only Makeup / Fragrance Section 03 and Section 04 items,
applies the strict W27 item-level date filter, deduplicates repeated products
across weeks, preserves provenance for every occurrence, and writes the result
to ``data/months/2026-06/recovered_candidates.json``.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "months" / "2026-06"
OUTPUT_PATH = OUTPUT_DIR / "recovered_candidates.json"

HISTORICAL_COMMIT = "709c63b"
PROVENANCE_URL = f"https://github.com/edeleneguo/beauty-weekly/commit/{HISTORICAL_COMMIT}"

ARCHIVE_FILES = {
    "week-23": {
        "makeup": "archive/week-23/index.html",
        "fragrance": "archive/week-23/fragrance.html",
    },
    "week-25": {
        "makeup": "archive/week-25/index.html",
        "fragrance": "archive/week-25/fragrance.html",
    },
    "week-26": {
        "makeup": "archive/week-26/index.html",
        "fragrance": "archive/week-26/fragrance.html",
    },
    "week-27": {
        "makeup": "archive/week-27/index.html",
        "fragrance": "archive/week-27/fragrance.html",
    },
}

SECTION_LABELS = {
    "heat_rankings": "Section 03",
    "new_product_radar": "Section 04",
}

SECTION_HTML_CLASS = {
    "heat_rankings": "heat-section",
    "new_product_radar": "radar-section",
}

PANEL_LABEL_TO_KEY = {
    ("US", "LUXURY"): "US LUXURY",
    ("US", "MASSTIGE"): "US MASSTIGE",
    ("CN", "LUXURY"): "CN LUXURY",
    ("CN", "MASSTIGE"): "CN MASSTIGE",
}

DETAIL_KEY_MAP = {
    "price/link": "price_link",
    "价格": "price_link",
    "key features": "key_features",
    "核心卖点": "key_features",
    "notes & longevity": "key_features",
    "notes & positioning": "key_features",
    "buzz/reviews/sales": "buzz",
    "社媒热度": "buzz",
    "brand/positioning": "brand",
    "口碑": "brand",
    "brand/gender/occasion": "brand",
    "launch/category": "brand",
    "新品类型": "brand",
    "上市日期": "key_features",
}

W27_ALLOWED_DATES = {"2026-06-29", "2026-06-30"}


def _run_git_show(path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{HISTORICAL_COMMIT}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_tags(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", "", text)
    return _normalize_space(html.unescape(no_tags))


def _slug(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _extract_section(content: str, section_key: str) -> str:
    section_class = SECTION_HTML_CLASS[section_key]
    heading_markers = (
        ("Heat Rankings", SECTION_LABELS[section_key])
        if section_key == "heat_rankings"
        else ("New Product Radar", SECTION_LABELS[section_key])
    )
    for heading_match in re.finditer(
        r'<h2\s+class="section-title"[^>]*>(.*?)</h2>',
        content,
        re.DOTALL,
    ):
        heading_text = _strip_tags(heading_match.group(1))
        if not any(marker in heading_text for marker in heading_markers):
            continue
        section_start = content.find(f'<div class="{section_class}"', heading_match.end())
        if section_start == -1:
            continue
        body_start = content.find(">", section_start)
        next_heading = content.find('<h2 class="section-title"', body_start)
        appendix = content.find("<!-- APPENDIX", body_start)
        generic_section = content.find('<div class="section">', body_start)
        candidates = [idx for idx in (next_heading, appendix, generic_section) if idx != -1]
        body_end = min(candidates) if candidates else len(content)
        return content[body_start + 1 : body_end]

    if section_key == "heat_rankings":
        fallback = re.search(
            r"<!--.*?Heat.*?-->\s*<div class=\"heat-section\">(.*?)(?=<!--.*?Radar.*?-->)",
            content,
            re.DOTALL,
        )
    else:
        fallback = re.search(
            r"<!--.*?Radar.*?-->\s*(.*?)(?=<!--\s+APPENDIX|<div class=\"section\">\s*<h3)",
            content,
            re.DOTALL,
        )
    return fallback.group(1) if fallback else ""


def _extract_panels(section_html: str) -> list[tuple[str, str]]:
    panels: list[tuple[str, str]] = []
    h4_matches = list(re.finditer(r"<h4[^>]*>(.*?)</h4>", section_html, re.DOTALL))
    for idx, heading in enumerate(h4_matches):
        heading_html = heading.group(1)
        market_match = re.search(r"<span[^>]*>(US|CN)</span>", heading_html)
        tier_match = re.search(r"<span[^>]*>(LUXURY|MASSTIGE)</span>", heading_html)
        start = heading.end()
        end = h4_matches[idx + 1].start() if idx + 1 < len(h4_matches) else len(section_html)
        body_html = section_html[start:end]
        if market_match and tier_match:
            panel_key = PANEL_LABEL_TO_KEY[(market_match.group(1), tier_match.group(1))]
        else:
            heading_text = _strip_tags(heading_html).upper()
            market = "CN" if ("CHINA" in heading_text or "CN" in heading_text) else "US"
            if "MASSTIGE" in heading_text:
                tier = "MASSTIGE"
            elif "LUXURY" in heading_text or "PRESTIGE" in heading_text or "奢品" in heading_text:
                tier = "LUXURY"
            else:
                tier = "LEGACY"
            panel_key = f"{market} {tier}"
        if panel_key.endswith("LEGACY"):
            h5_matches = list(re.finditer(r"<h5[^>]*>(.*?)</h5>", body_html, re.DOTALL))
            if h5_matches:
                for sub_idx, sub_heading in enumerate(h5_matches):
                    sub_text = _strip_tags(sub_heading.group(1)).upper()
                    if "MASSTIGE" in sub_text or "精品彩妆" in sub_text:
                        tier = "MASSTIGE"
                    elif "LUXURY" in sub_text or "PRESTIGE" in sub_text or "奢品" in sub_text:
                        tier = "LUXURY"
                    else:
                        continue
                    sub_start = sub_heading.end()
                    sub_end = (
                        h5_matches[sub_idx + 1].start()
                        if sub_idx + 1 < len(h5_matches)
                        else len(body_html)
                    )
                    panels.append((f"{market} {tier}", body_html[sub_start:sub_end]))
                continue
        panels.append((panel_key, body_html))
    return panels


def _extract_detail_cells(item_html: str) -> dict[str, dict[str, str]]:
    cells: dict[str, dict[str, str]] = {}
    matches = re.findall(
        r'<div\s+class="heat-detail-cell(?:\s+[^"]*)?">\s*'
        r'<div\s+class="heat-detail-label">(.*?)</div>\s*'
        r'<div\s+class="heat-detail-value">(.*?)</div>\s*'
        r"</div>",
        item_html,
        re.DOTALL,
    )
    for label_html, value_html in matches:
        trend_tag_match = re.search(r'<span\s+class="heat-trend-tag">([^<]+)</span>', label_html)
        key = _map_detail_key(_slug(_strip_tags(label_html)))
        if key is None:
            continue
        link_match = re.search(r'<a\s+href="([^"]+)"', value_html)
        text_value = _strip_tags(re.sub(r'<a\s+[^>]*>.*?</a>', "", value_html, flags=re.DOTALL))
        cell = {"value": text_value, "link": link_match.group(1) if link_match else ""}
        if trend_tag_match:
            cell["trend_tag"] = _normalize_space(html.unescape(trend_tag_match.group(1)))
        cells[key] = cell

    if cells:
        return cells

    legacy_matches = re.findall(
        r"<div>\s*<div class=\"cell-label\">(.*?)</div>\s*"
        r"<div class=\"(?:cell-value|cell-tags)\">(.*?)</div>\s*</div>",
        item_html,
        re.DOTALL,
    )
    for label_html, value_html in legacy_matches:
        key = _map_detail_key(_slug(_strip_tags(label_html)))
        if key is None:
            continue
        link_match = re.search(r'<a\s+href="([^"]+)"', value_html)
        text_value = _strip_tags(re.sub(r'<a\s+[^>]*>.*?</a>', "", value_html, flags=re.DOTALL))
        cells[key] = {"value": text_value, "link": link_match.group(1) if link_match else ""}
    return cells


def _map_detail_key(label_slug: str) -> str | None:
    for prefix, key in DETAIL_KEY_MAP.items():
        if label_slug.startswith(prefix):
            return key
    return None


def _extract_iso_dates(text: str) -> list[str]:
    dates: set[str] = set()
    for year, month, day in re.findall(r"\b(2026)[./-](0?6)[./-](\d{1,2})\b", text):
        dates.add(f"{year}-{int(month):02d}-{int(day):02d}")

    month_names = {"jun": 6, "june": 6}
    for month_name, day in re.findall(r"\b(Jun(?:e)?)\s+(\d{1,2})(?:,\s*2026)?\b", text, re.I):
        month = month_names[month_name.casefold()]
        dates.add(f"2026-{month:02d}-{int(day):02d}")

    for month, day in re.findall(r"(0?6)\s*月\s*(\d{1,2})\s*日", text):
        dates.add(f"2026-{int(month):02d}-{int(day):02d}")

    return sorted(dates)


def _extract_span_contents(item_html: str, class_name: str) -> str | None:
    match = re.search(
        rf'<span\s+class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>',
        item_html,
    )
    if match is None:
        return None

    tag_iter = re.finditer(r"</?span\b[^>]*>", item_html[match.end() :], re.DOTALL)
    depth = 1
    for tag in tag_iter:
        if tag.group(0).startswith("</span"):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            start = match.end()
            end = start + tag.start()
            return item_html[start:end]
    return None


def _extract_numeric_score(item_html: str) -> int | None:
    score_match = re.search(r'<span\s+class="heat-score">(\d+)</span>', item_html)
    legacy_score_match = re.search(r'<span\s+class="heat-score-val">(\d+)%?</span>', item_html)
    if score_match:
        return int(score_match.group(1))
    if legacy_score_match:
        return int(legacy_score_match.group(1))

    fill_match = re.search(r'heat-fill[^"]*"[^>]*style="[^"]*width:\s*(\d+)%', item_html)
    if fill_match:
        return int(fill_match.group(1))
    return None


def _parse_item(
    item_html: str,
    *,
    topic: str,
    section: str,
    panel: str,
    week: str,
    path: str,
) -> dict[str, Any]:
    market_match = re.search(r'<span\s+class="heat-rank\s+(us|cn)"[^>]*>(\d+)</span>', item_html)
    legacy_rank_match = re.search(r'<span\s+class="heat-rank[^"]*"[^>]*>(\d+)</span>', item_html)
    if not market_match and not legacy_rank_match:
        raise ValueError(f"Unable to parse rank/market for {topic} {section} {panel}")

    detail = _extract_detail_cells(item_html)
    if market_match:
        rank = int(market_match.group(2))
        market = market_match.group(1).upper()
    else:
        rank = int(legacy_rank_match.group(1))
        market = panel.split()[0]
    tier = panel.split()[1] if " " in panel else "LEGACY"
    trend_badge_match = re.search(
        r'<span\s+class="heat-trend-badge">([^<]+)</span>',
        item_html,
    )
    legacy_trend_match = re.search(
        r'<span\s+class="trend-product-tag[^"]*">([^<]+)</span>',
        item_html,
    )
    new_badge_match = re.search(r'<span\s+class="heat-new-badge">([^<]+)</span>', item_html)
    score = _extract_numeric_score(item_html)
    product_name_html = _extract_span_contents(item_html, "heat-name")
    category_match = re.search(r'<span\s+class="heat-cat-badge">([^<]+)</span>', item_html)
    if category_match is None:
        category_match = re.search(r'<span\s+class="prod-cat-tag[^"]*">([^<]+)</span>', item_html)

    if not product_name_html or score is None:
        raise ValueError(f"Unable to parse core product fields for {topic} {section} {panel}")

    combined_text = _strip_tags(item_html)
    explicit_dates = _extract_iso_dates(combined_text)
    platform_line_match = re.search(
        r'<div\s+class="heat-platform-line">(.*?)</div>',
        item_html,
        re.DOTALL,
    )
    platform_line = _strip_tags(platform_line_match.group(1)) if platform_line_match else ""
    launch_text = detail.get("brand", {}).get("value", "")
    price_text = detail.get("price_link", {}).get("value", "")
    link = detail.get("price_link", {}).get("link", "")
    key_features = detail.get("key_features", {}).get("value", "")
    if not launch_text and platform_line:
        launch_text = platform_line

    return {
        "topic": topic,
        "section": section,
        "panel": panel,
        "market": market,
        "tier": tier,
        "rank": rank,
        "score": score,
        "product_name": _normalize_space(
            _strip_tags(
                re.sub(
                    r'<span\s+class="trend-product-tag[^"]*">.*?</span>',
                    "",
                    product_name_html,
                )
            )
        ),
        "category_badge": (
            _normalize_space(html.unescape(category_match.group(1))) if category_match else ""
        ),
        "trend_badge": (
            _normalize_space(html.unescape(trend_badge_match.group(1)))
            if trend_badge_match
            else ("Trend" if legacy_trend_match else None)
        ),
        "new_badge": (
            _normalize_space(html.unescape(new_badge_match.group(1))) if new_badge_match else None
        ),
        "trend_tag": detail.get("key_features", {}).get("trend_tag"),
        "launch_text": launch_text,
        "explicit_dates": explicit_dates,
        "detail": {
            "price_text": price_text,
            "price_link": link,
            "key_features": key_features,
            "buzz": detail.get("buzz", {}).get("value", ""),
            "brand": launch_text,
        },
        "source_snapshot": {
            "commit": HISTORICAL_COMMIT,
            "commit_url": PROVENANCE_URL,
            "week": week,
            "path": path,
        },
    }


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        candidate["topic"],
        candidate["section"],
        candidate["panel"],
        _slug(candidate["product_name"]),
    )


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, int, int]:
    detail = candidate.get("detail", {})
    filled_detail_cells = sum(1 for value in detail.values() if value)
    snapshot = candidate.get("source_snapshot")
    if snapshot is None:
        snapshot = candidate.get("provenance", [{}])[-1]
    week_number = int(snapshot["week"].split("-")[1])
    has_exact_date = 1 if candidate.get("explicit_dates") else 0
    return (
        filled_detail_cells,
        has_exact_date,
        week_number,
        candidate["score"],
        -candidate["rank"],
    )


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    duplicate_count = 0

    for candidate in candidates:
        key = _candidate_key(candidate)
        existing = merged.get(key)
        if existing is None:
            candidate["provenance"] = [candidate.pop("source_snapshot")]
            merged[key] = candidate
            continue

        duplicate_count += 1
        existing["provenance"].append(candidate["source_snapshot"])
        if _candidate_sort_key(candidate) > _candidate_sort_key(existing):
            provenance = existing["provenance"]
            candidate["provenance"] = provenance
            merged[key] = candidate

    deduped = sorted(
        merged.values(),
        key=lambda item: (
            item["topic"],
            item["section"],
            item["panel"],
            -item["score"],
            item["rank"],
            item["product_name"].casefold(),
        ),
    )
    return deduped, duplicate_count


def _should_include_candidate(week: str, candidate: dict[str, Any]) -> bool:
    if week != "week-27":
        return True
    return bool(set(candidate["explicit_dates"]) & W27_ALLOWED_DATES)


def _recover_all_candidates() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    per_week_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    excluded_w27 = 0
    parse_failures = 0

    for week, topic_paths in ARCHIVE_FILES.items():
        for topic, archive_path in topic_paths.items():
            page_html = _run_git_show(archive_path)
            for section in ("heat_rankings", "new_product_radar"):
                section_html = _extract_section(page_html, section)
                if not section_html:
                    continue
                for panel, panel_html in _extract_panels(section_html):
                    item_blocks = re.findall(
                        r'<li\s+class="heat-item">(.*?)</li>',
                        panel_html,
                        re.DOTALL,
                    )
                    for item_html in item_blocks:
                        try:
                            candidate = _parse_item(
                                item_html,
                                topic=topic,
                                section=section,
                                panel=panel,
                                week=week,
                                path=archive_path,
                            )
                        except ValueError:
                            parse_failures += 1
                            per_week_counts[week]["parse_failures"] += 1
                            continue
                        if _should_include_candidate(week, candidate):
                            recovered.append(candidate)
                            per_week_counts[week]["included"] += 1
                            per_week_counts[week][f"{topic}_{section}"] += 1
                        else:
                            excluded_w27 += 1
                            per_week_counts[week]["excluded"] += 1

    deduped, duplicate_count = _dedupe_candidates(recovered)
    summary = {
        "raw_included": len(recovered),
        "raw_excluded_w27": excluded_w27,
        "deduped_unique": len(deduped),
        "duplicates_removed": duplicate_count,
        "parse_failures": parse_failures,
        "per_week": {week: dict(counts) for week, counts in sorted(per_week_counts.items())},
    }
    return deduped, summary


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates, summary = _recover_all_candidates()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "historical_snapshot": HISTORICAL_COMMIT,
        "historical_snapshot_url": PROVENANCE_URL,
        "month": "2026-06",
        "window_start": "2026-06-01",
        "window_end": "2026-06-30",
        "included_weeks": ["week-23", "week-25", "week-26", "week-27"],
        "w27_rule": "Only keep W27 items with explicit item-level June 29 or June 30 dates.",
        "summary": summary,
        "candidates": candidates,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("=== JUNE RECOVERY SUMMARY ===")
    print(f"Raw included items: {summary['raw_included']}")
    print(f"Raw W27 exclusions: {summary['raw_excluded_w27']}")
    print(f"Duplicates removed: {summary['duplicates_removed']}")
    print(f"Unique recovered candidates: {summary['deduped_unique']}")
    print(f"Output written to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
