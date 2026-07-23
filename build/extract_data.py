#!/usr/bin/env python3
"""LEGACY ONE-TIME IMPORT TOOL — not a production pipeline entrypoint.

Extract canonical product data from Week 28 HTML files.

Reads from a pristine HTML backup (data/html_pristine/) rather than root
files, so re-running the pipeline never overwrites manual canonical fixes
in data/week28.json.

Design invariants
-----------------
* One JSON record per unique (file_key, section, market, tier, rank).
* No global split/join mutation – each product is processed independently.
* Language-specific detail cells are stored as {en: ..., cn: ...} dicts
  so that a single record edit propagates to all rendered variants.
* Existing HTML and archive files are never modified.
* Idempotent: will not overwrite an existing week28.json.
"""

import json
import os
import re
import html as html_mod
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUTPUT = os.path.join(DATA_DIR, "week28.json")

# Pristine HTML source: one-time import from a known-good git commit
# The extractor reads from data/html_pristine/ (never from root HTML files)
PRISTINE_DIR = os.path.join(DATA_DIR, "html_pristine")

# Canonical file keys – order matters for deterministic output
FILE_KEYS = [
    ("index.html", "makeup"),
    ("fragrance.html", "fragrance"),
]

# Detail-cell labels we expect per section type
HEAT_CELL_LABELS_EN = [
    "Price/Link",
    "Key Features",
    "Buzz/Reviews/Sales",
    "Brand/Positioning",
]
HEAT_CELL_LABELS_CN = ["价格/链接", "核心卖点", "社媒热度/口碑/销量", "品牌/产品定位"]
RADAR_CELL_LABELS_EN = [
    "Price/Link",
    "Key Features",
    "Buzz/Reviews/Sales",
    "Launch/Category",
]
RADAR_CELL_LABELS_CN = [
    "价格/链接",
    "核心卖点",
    "社媒热度/口碑/销量",
    "上市日期/新品类目",
]

# Canonical detail cell keys (4 cells always)
DETAIL_KEYS = ["price_link", "key_features", "buzz", "brand"]


# ---------------------------------------------------------------------------
# HTML helpers (stdlib only – no beautifulsoup dependency)
# ---------------------------------------------------------------------------


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(text).strip()


def _find_span_text(segment: str, class_name: str) -> Optional[str]:
    pattern = r'<span\s+class="{0}"[^>]*>([^<]*)</span>'.format(re.escape(class_name))
    m = re.search(pattern, segment)
    if m:
        return html_mod.unescape(m.group(1).strip())
    return None


def _find_link_url(segment: str) -> Optional[str]:
    m = re.search(r'<a\s+href="([^"]*)"', segment)
    if m:
        return html_mod.unescape(m.group(1))
    return None


def _find_trend_tags(text_html: str) -> List[str]:
    tags = re.findall(r'<span\s+class="heat-trend-tag"[^>]*>([^<]*)</span>', text_html)
    return [html_mod.unescape(t.strip()) for t in tags if t.strip()]


def _extract_balanced(html_str: str, tag: str, start_pos: int) -> Optional[str]:
    open_m = re.search(r"<" + re.escape(tag) + r"[\s>]", html_str[start_pos:])
    if not open_m:
        return None
    content_start = start_pos + open_m.end()
    depth = 1
    pos = content_start
    while depth > 0 and pos < len(html_str):
        next_open = re.search(r"<{0}[\s>]".format(tag), html_str[pos:])
        next_close = re.search(r"</{0}>".format(tag), html_str[pos:])
        if next_close is None:
            break
        if next_open and next_open.start() < next_close.start():
            depth += 1
            pos += next_open.end()
        else:
            depth -= 1
            if depth == 0:
                return html_str[content_start : pos + next_close.start()]
            pos += next_close.end()
    return None


def _parse_detail_cells(detail_html: str) -> List[Dict[str, Any]]:
    cells: List[Dict[str, Any]] = []
    grid = _extract_balanced(detail_html, "div", 0)
    if not grid:
        return cells
    parts = re.split(r'<div\s+class="heat-detail-cell(?:\s+full-width)?"[^>]*>', grid)
    for part in parts[1:]:
        label_m = re.search(r'<div\s+class="heat-detail-label"[^>]*>(.*?)</div>', part, re.DOTALL)
        value_m = re.search(r'<div\s+class="heat-detail-value"[^>]*>(.*?)</div>', part, re.DOTALL)
        label_html = label_m.group(1) if label_m else ""
        value_html = value_m.group(1) if value_m else ""
        trend_tags = _find_trend_tags(label_html)
        label = _strip_tags(label_html)
        value = _strip_tags(value_html)
        link = _find_link_url(value_html)
        cell: Dict[str, Any] = {"label": label, "value": value}
        if link:
            cell["link"] = link
        if trend_tags:
            cell["trend_tags"] = trend_tags
        cells.append(cell)
    return cells


def _parse_heat_item(item_html: str) -> Dict[str, Any]:
    product: Dict[str, Any] = {}
    rank_m = re.search(r'<span\s+class="heat-rank\s+(us|cn)"[^>]*>(\d+)</span>', item_html)
    if rank_m:
        product["rank"] = int(rank_m.group(2))
        product["market"] = rank_m.group(1).upper()
    name = _find_span_text(item_html, "heat-name")
    if name:
        product["name"] = name
    cat = _find_span_text(item_html, "heat-cat-badge")
    if cat:
        # Fix EDP spacing: "FloralEDP" → "Floral EDP"
        cat = re.sub(r"(\w)(EDP)\b", r"\1 \2", cat)
        product["category_badge"] = cat
    trend = _find_span_text(item_html, "heat-trend-badge")
    if trend:
        product["trend_badge"] = trend
    new_badge = _find_span_text(item_html, "heat-new-badge")
    if new_badge:
        product["new_badge"] = new_badge
    score = _find_span_text(item_html, "heat-score")
    if score:
        try:
            product["score"] = int(score)
        except ValueError:
            product["score"] = score
    detail_m = re.search(r'<div\s+class="heat-detail"[^>]*>', item_html)
    if detail_m:
        detail_inner = _extract_balanced(item_html, "div", detail_m.start())
        if detail_inner:
            product["detail_cells"] = _parse_detail_cells(detail_inner)
    return product


def _parse_panel(panel_html: str) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    items = re.split(r'<li\s+class="heat-item"[^>]*>', panel_html)
    for item_html in items[1:]:
        products.append(_parse_heat_item(item_html))
    return products


def _extract_panels(section_html: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return {panel_key: [products]} where panel_key = 'US LUXURY' etc."""
    panels: Dict[str, List[Dict[str, Any]]] = {}
    h4_matches = list(re.finditer(r"<h4[^>]*>(.*?)</h4>", section_html, re.DOTALL))
    panel_h4s = []
    for m in h4_matches:
        inner = m.group(1)
        market_m = re.search(r"<span[^>]*>(US|CN)</span>", inner)
        tier_m = re.search(r"<span[^>]*>(LUXURY|MASSTIGE)</span>", inner)
        if market_m and tier_m:
            panel_h4s.append(
                {"start": m.end(), "market": market_m.group(1), "tier": tier_m.group(1)}
            )
    for i, h4 in enumerate(panel_h4s):
        start = h4["start"]
        if i + 1 < len(panel_h4s):
            next_h4_pos = section_html.rfind("<h4", start, panel_h4s[i + 1]["start"])
            end = next_h4_pos if next_h4_pos > start else panel_h4s[i + 1]["start"]
        else:
            end = len(section_html)
        key = "{0} {1}".format(h4["market"], h4["tier"])
        panels[key] = _parse_panel(section_html[start:end])
    return panels


def _extract_section(content: str, section_name: str) -> Dict[str, List[Dict[str, Any]]]:
    if section_name == "heat":
        m = re.search(
            r'Section 03</span>\s*</h2>\s*<div\s+class="heat-section"[^>]*>(.*?)'
            r'(?=<h2\s+class="section-title")',
            content,
            re.DOTALL,
        )
    else:
        m = re.search(
            r'Section 04</span>\s*</h2>\s*<div\s+class="radar-section"[^>]*>(.*?)'
            r'(?=<h2\s+class="section-title"|<!--\s+APPENDIX|<div\s+class="appendix|<script|$)',
            content,
            re.DOTALL,
        )
    if not m:
        return {}
    return _extract_panels(m.group(1))


# ---------------------------------------------------------------------------
# Canonicalisation: merge EN + CN into single language-paired records
# ---------------------------------------------------------------------------


def _cell_label_to_key(label: str, section: str) -> str:
    """Map a detail-cell label to one of the four canonical keys."""
    mapping = {
        "Price/Link": "price_link",
        "价格/链接": "price_link",
        "Key Features": "key_features",
        "核心卖点": "key_features",
        "Buzz/Reviews/Sales": "buzz",
        "社媒热度/口碑/销量": "buzz",
        "Brand/Positioning": "brand",
        "品牌/产品定位": "brand",
        "Launch/Category": "brand",
        "上市日期/新品类目": "brand",
    }
    # Handle trend-signal labels
    for prefix in ("Key Features Trend Signal", "Key Features 趋势信号"):
        if label.startswith(prefix.split()[0]):
            return "key_features"
    return mapping.get(label, label.lower().replace(" ", "_").replace("/", "_"))


def _normalise_detail_cells(cells: List[Dict[str, Any]], section: str) -> Dict[str, Dict[str, Any]]:
    """Convert a flat list of detail cells into {key: {value, link?, trend_tags?}}."""
    result: Dict[str, Dict[str, Any]] = {}
    for cell in cells:
        key = _cell_label_to_key(cell["label"], section)
        entry: Dict[str, Any] = {"value": cell["value"]}
        if "link" in cell:
            entry["link"] = cell["link"]
        if "trend_tags" in cell:
            entry["trend_tags"] = cell["trend_tags"]
        result[key] = entry
    return result


def _merge_panels(
    panels_en: Dict[str, List[Dict[str, Any]]],
    panels_cn: Dict[str, List[Dict[str, Any]]],
    section: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Merge EN and CN panels into canonical records keyed by panel.

    Uses EN as the primary product selection. CN provides translated detail
    cell values. If a product exists only in CN, it's included with CN as
    the primary name/category.
    """
    all_keys = list(dict.fromkeys(list(panels_en.keys()) + list(panels_cn.keys())))
    merged: Dict[str, List[Dict[str, Any]]] = {}
    for key in all_keys:
        en_products = panels_en.get(key, [])
        cn_products = panels_cn.get(key, [])
        # Use EN as primary if available, otherwise CN
        primary_products = en_products if en_products else cn_products
        secondary_products = cn_products if en_products else []
        # Index secondary by rank for translation lookup
        secondary_by_rank: Dict[int, Dict[str, Any]] = {}
        for p in secondary_products:
            r = p.get("rank")
            if r is not None:
                secondary_by_rank[r] = p
        records: List[Dict[str, Any]] = []
        seen_ranks: set = set()
        for p in primary_products:
            rank = p.get("rank", 0)
            # Skip duplicates: keep only first occurrence per rank
            if rank in seen_ranks:
                continue
            seen_ranks.add(rank)
            # Skip placeholder products with score 0 or placeholder names
            score = p.get("score", 0)
            name = p.get("name", "")
            if isinstance(score, int) and score == 0:
                continue
            if "no more signal" in name.lower() or "placeholder" in name.lower():
                continue
            market = p.get("market", key.split()[0])
            tier = key.split()[-1] if " " in key else "LUXURY"
            cn_p = secondary_by_rank.get(rank, {})
            record: Dict[str, Any] = {
                "rank": rank,
                "market": market,
                "tier": tier,
                "name": p.get("name", ""),
                "category_badge": p.get("category_badge", ""),
            }
            # Optional badges
            if p.get("trend_badge"):
                record["trend_badge"] = p["trend_badge"]
            elif cn_p.get("trend_badge"):
                record["trend_badge"] = cn_p["trend_badge"]
            if p.get("new_badge"):
                record["new_badge"] = p["new_badge"]
            elif cn_p.get("new_badge"):
                record["new_badge"] = cn_p["new_badge"]
            record["score"] = p.get("score", 0)
            # Detail cells: EN primary, CN secondary
            en_cells = _normalise_detail_cells(p.get("detail_cells", []), section)
            cn_cells = _normalise_detail_cells(cn_p.get("detail_cells", []), section)
            detail: Dict[str, Any] = {}
            for dkey in DETAIL_KEYS:
                en_entry = en_cells.get(dkey, {})
                cn_entry = cn_cells.get(dkey, {})
                merged_entry: Dict[str, Any] = {}
                if en_entry.get("value"):
                    merged_entry["en"] = en_entry["value"]
                if cn_entry.get("value"):
                    merged_entry["cn"] = cn_entry["value"]
                link = en_entry.get("link") or cn_entry.get("link")
                if link:
                    merged_entry["link"] = link
                tags = en_entry.get("trend_tags") or cn_entry.get("trend_tags")
                if tags:
                    merged_entry["trend_tags"] = tags
                if merged_entry:
                    detail[dkey] = merged_entry
            record["detail"] = detail
            records.append(record)
        merged[key] = records
    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def extract_file(filepath: str) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    return {
        "heat_rankings": _extract_section(content, "heat"),
        "new_product_radar": _extract_section(content, "radar"),
    }


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    # Idempotency guard: do not overwrite manual canonical fixes
    if os.path.exists(OUTPUT):
        print(
            "SKIP: {0} already exists. To re-extract from pristine HTML, "
            "delete the file first or run: rm {0}".format(OUTPUT)
        )
        return

    # Determine source directory: pristine backup or fall back to root
    if os.path.isdir(PRISTINE_DIR):
        source_dir = PRISTINE_DIR
        print("Reading from pristine backup: {0}".format(PRISTINE_DIR))
    else:
        source_dir = ROOT
        print("WARNING: No pristine backup found, reading from root HTML files")

    extracted: Dict[str, Any] = {}
    for fname, topic in FILE_KEYS:
        fpath = os.path.join(source_dir, fname)
        if not os.path.exists(fpath):
            print("WARNING: {0} not found".format(fpath), flush=True)
            continue
        data = extract_file(fpath)
        lang = "en" if not fname.endswith("-cn.html") else "cn"
        key = "{0}_{1}".format(topic, lang)
        extracted[key] = data

    # Build canonical merged records
    canonical: Dict[str, Any] = {
        "week": 28,
        "date_range": "Jul 7 – Jul 13, 2026",
        "date_range_cn": "7月7日 – 7月13日",
        "version": "week28-v1",
        "version_en_makeup": "week28-en-20260713-v1",
        "version_cn_makeup": "week28-cn-20260713-v1",
        "version_en_fragrance": "week28-fragrance-en-20260713-v1",
        "version_cn_fragrance": "week28-fragrance-cn-20260713-v1",
        "products": {},
    }

    for topic in ("makeup", "fragrance"):
        en_data = extracted.get("{0}_en".format(topic), {})
        cn_data = extracted.get("{0}_cn".format(topic), {})
        en_heat = en_data.get("heat_rankings", {})
        cn_heat = cn_data.get("heat_rankings", {})
        en_radar = en_data.get("new_product_radar", {})
        cn_radar = cn_data.get("new_product_radar", {})

        canonical["products"][topic] = {
            "heat_rankings": _merge_panels(en_heat, cn_heat, "heat"),
            "new_product_radar": _merge_panels(en_radar, cn_radar, "radar"),
        }

    # Deterministic JSON output
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(canonical, f, ensure_ascii=False, indent=2, sort_keys=False)

    # Summary
    for topic in ("makeup", "fragrance"):
        prods = canonical["products"][topic]
        for section in ("heat_rankings", "new_product_radar"):
            for panel, items in prods[section].items():
                print("{0}/{1}/{2}: {3} products".format(topic, section, panel, len(items)))


if __name__ == "__main__":
    main()
