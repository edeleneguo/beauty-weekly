#!/usr/bin/env python3
"""generate_weekly.py — Generate canonical weekly dataset using LLM API.

Outputs report.json, sources.json, scoring.json, manifest.json in the EXACT
format expected by the Pydantic models and existing render/validate pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.week import current_iso_week  # noqa: E402

API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


def iso_week_date_range(week_str: str) -> tuple[str, str, str, str]:
    year, week = int(week_str[:4]), int(week_str[-2:])
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    en_range = f"{monday.strftime('%b')} {monday.day} \u2013 {sunday.strftime('%b')} {sunday.day}, {monday.year}"
    cn_range = f"{monday.month}\u6708{monday.day}\u65e5 \u2013 {sunday.month}\u6708{sunday.day}\u65e5"
    return en_range, cn_range, monday.isoformat(), sunday.isoformat()


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> str:
    if not API_KEY:
        raise ValueError("LLM_API_KEY environment variable not set")
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode("utf-8")
    url = f"{BASE_URL}/chat/completions"
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]


def parse_json_response(response: str) -> dict:
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(response)


def make_product(name: str, name_cn: str, rank: int, score: int, market: str,
                 tier: str, category_badge: str, brand_cn: str, brand_en: str,
                 buzz_cn: str, buzz_en: str, features_cn: str, features_en: str,
                 price_cn: str, price_en: str, link: str,
                 trend_badge: str = None, new_badge: str = None,
                 launch_evidence: dict = None) -> dict:
    """Create a product in the exact canonical format."""
    return {
        "category_badge": category_badge,
        "detail": {
            "brand": {"cn": brand_cn, "en": brand_en},
            "buzz": {"cn": buzz_cn, "en": buzz_en},
            "key_features": {"cn": features_cn, "en": features_en},
            "price_link": {"cn": price_cn, "en": price_en, "link": link},
        },
        "launch_evidence": launch_evidence,
        "market": market,
        "name": name,
        "name_cn": name_cn,
        "new_badge": new_badge,
        "rank": rank,
        "score": score,
        "tier": tier,
        "trend": None,
        "trend_badge": trend_badge,
    }


def generate_products(raw_data: dict, category: str, iso_week: str, en_range: str) -> dict:
    """Generate products for a category using LLM, returning canonical format."""
    articles_text = "\n".join(
        f"- [{a['source']}] {a['title']}: {a.get('summary', '')[:200]}"
        for a in raw_data.get("articles", [])[:30]
    )

    system_prompt = f"""You are a beauty industry analyst. Generate product data for the {category} category.
Output ONLY valid JSON with this exact structure:
{{
  "heat_rankings": {{
    "US LUXURY": [
      {{
        "name": "Product Name",
        "name_cn": "产品中文名",
        "rank": 1,
        "score": 88,
        "market": "US",
        "tier": "LUXURY",
        "category_badge": "Foundation",
        "brand_cn": "品牌定位描述",
        "brand_en": "Brand positioning",
        "buzz_cn": "口碑数据",
        "buzz_en": "Buzz data",
        "features_cn": "核心卖点",
        "features_en": "Key features",
        "price_cn": "$XX",
        "price_en": "$XX",
        "link": "https://www.sephora.com/product/..."
      }}
    ],
    "US MASSTIGE": [...],
    "CN LUXURY": [...],
    "CN MASSTIGE": [...]
  }},
  "new_product_radar": {{
    "US LUXURY": [...],
    "US MASSTIGE": [...],
    "CN LUXURY": [],
    "CN MASSTIGE": []
  }}
}}

Rules:
- Generate 5-10 products per heat_rankings panel
- Generate 2-5 new products per radar panel (only products launched within 4 weeks)
- All products must be REAL, publicly available {category} products
- Scores: 65-98 range (85=Trending, 90=Viral)
- CN fields in Chinese, EN in English
- Links must be real Sephora/Ulta/Tmall URLs
- Use real buzz data (review counts, sales rankings, social media metrics)"""

    user_prompt = f"Generate {category} product data for ISO Week {iso_week} ({en_range}).\n\nRaw data:\n{articles_text}"

    print(f"  Calling LLM for {category} products...")
    response = call_llm(system_prompt, user_prompt)
    data = parse_json_response(response)

    # Transform to canonical format
    result = {"heat_rankings": {}, "new_product_radar": {}}
    for section in ["heat_rankings", "new_product_radar"]:
        if section in data:
            for panel, products in data[section].items():
                canonical_products = []
                if isinstance(products, list):
                    for p in products:
                        if isinstance(p, dict):
                            canonical_products.append(make_product(
                                name=p.get("name", ""),
                                name_cn=p.get("name_cn"),
                                rank=p.get("rank", 1),
                                score=p.get("score", 75),
                                market=p.get("market", panel.split()[0]),
                                tier=p.get("tier", panel.split()[1] if len(panel.split()) > 1 else "LUXURY"),
                                category_badge=p.get("category_badge", ""),
                                brand_cn=p.get("brand_cn", ""),
                                brand_en=p.get("brand_en", ""),
                                buzz_cn=p.get("buzz_cn", ""),
                                buzz_en=p.get("buzz_en", ""),
                                features_cn=p.get("features_cn", ""),
                                features_en=p.get("features_en", ""),
                                price_cn=p.get("price_cn", ""),
                                price_en=p.get("price_en", ""),
                                link=p.get("link", ""),
                                trend_badge=p.get("trend_badge"),
                                new_badge=p.get("new_badge"),
                                launch_evidence=p.get("launch_evidence"),
                            ))
                result[section][panel] = canonical_products
    return result


def main() -> int:
    iso_week = current_iso_week()
    en_range, cn_range, start_date, end_date = iso_week_date_range(iso_week)
    week_num = int(iso_week.split("-W")[1])

    print(f"=== Beauty Weekly Content Generation ===")
    print(f"ISO Week: {iso_week} (Week {week_num})")
    print(f"Date Range: {en_range}")
    print(f"LLM Model: {MODEL}")
    print()

    # Load raw data
    raw_path = ROOT / "data" / "weeks" / iso_week / "raw_collected.json"
    if not raw_path.exists():
        print(f"FATAL: {raw_path} not found. Run build/collect.py first.")
        return 1
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    print(f"Loaded raw data: {raw_data.get('total_articles', 0)} articles\n")

    # Generate products
    print("--- Generating Makeup Products ---")
    makeup = generate_products(raw_data, "makeup", iso_week, en_range)
    print(f"\n--- Generating Fragrance Products ---")
    fragrance = generate_products(raw_data, "fragrance", iso_week, en_range)

    # Build report.json (exact canonical format)
    report = {
        "date_range": en_range,
        "date_range_cn": cn_range,
        "products": {
            "makeup": makeup,
            "fragrance": fragrance,
        },
        "version": f"week{week_num}-2026{start_date.replace('-','')[:6]}-v1",
        "week": week_num,
    }

    # Build sources.json
    sources = {
        "schema_version": "2.0.0",
        "total_sources": len(raw_data.get("sources_fetched", [])),
        "sources": [
            {"name": s["name"], "url": s["url"], "type": s["type"], "status": "fetched"}
            for s in raw_data.get("sources_fetched", [])
        ],
        "articles": raw_data.get("articles", []),
    }

    # Build scoring.json
    all_products = []
    for cat in ["makeup", "fragrance"]:
        for section in ["heat_rankings", "new_product_radar"]:
            for panel, products in report["products"][cat][section].items():
                for p in products:
                    all_products.append({
                        "name": p.get("name", ""),
                        "panel": panel,
                        "score": p.get("score", 0),
                        "has_price": bool(p.get("detail", {}).get("price_link", {}).get("en")),
                        "has_url": bool(p.get("detail", {}).get("price_link", {}).get("link")),
                    })
    scoring = {
        "schema_version": "1.0.0",
        "scoring_formula": "Sales Score (\u226450) + Buzz Score (\u226450) = Total (\u2264100)",
        "recomputable": False,
        "products": all_products,
    }

    # Deterministic serialization
    def det_json(obj):
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)

    def sha256(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    report_json = det_json(report)
    sources_json = det_json(sources)
    scoring_json = det_json(scoring)

    report_hash = sha256(report_json)
    sources_hash = sha256(sources_json)
    scoring_hash = sha256(scoring_json)

    # Build manifest.json (exact format)
    manifest = {
        "canonical_hash": report_hash,
        "date_range": en_range,
        "date_range_cn": cn_range,
        "iso_week": iso_week,
        "note": "Auto-generated from public RSS data using LLM synthesis.",
        "phase": "auto",
        "schema_version": 3,
        "scoring_hash": scoring_hash,
        "sources_hash": sources_hash,
        "week": week_num,
    }
    manifest_json = det_json(manifest)

    # Write files
    output_dir = ROOT / "data" / "weeks" / iso_week
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "report.json": report_json,
        "sources.json": sources_json,
        "scoring.json": scoring_json,
        "manifest.json": manifest_json,
    }
    for fname, content in files.items():
        (output_dir / fname).write_text(content, encoding="utf-8")
        print(f"  {fname}: {len(content)} bytes")

    print(f"\n=== Generation Complete ===")
    print(f"Report hash: {report_hash[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
