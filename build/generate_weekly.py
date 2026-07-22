#!/usr/bin/env python3
"""generate_weekly.py — Generate canonical weekly dataset using LLM API.

Takes raw_collected.json (from collect.py) and generates the canonical
four-file set: report.json, sources.json, scoring.json, manifest.json.

Uses an OpenAI-compatible LLM API to synthesize trends, news, and product
rankings from the collected raw data.

Environment variables:
  LLM_API_KEY   — API key for the LLM provider (required)
  LLM_BASE_URL  — Base URL (default: https://api.openai.com/v1)
  LLM_MODEL     — Model name (default: gpt-4o-mini)

Output: data/weeks/<iso-week>/{report.json, sources.json, scoring.json, manifest.json}
"""
from __future__ import annotations

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

# --- LLM API Configuration ---
API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

# --- ISO Week helpers ---
def iso_week_date_range(week_str: str) -> tuple[str, str, str, str]:
    """Return (en_range, cn_range, start_date, end_date) for an ISO week string."""
    year, week = int(week_str[:4]), int(week_str[-2:])
    # ISO week starts on Monday
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    en_range = f"{monday.strftime('%b')} {monday.day} – {sunday.strftime('%b')} {sunday.day}, {monday.year}"
    cn_range = f"{monday.month}月{monday.day}日 – {sunday.month}月{sunday.day}日"
    return en_range, cn_range, monday.isoformat(), sunday.isoformat()


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> str:
    """Call an OpenAI-compatible LLM API."""
    if not API_KEY:
        raise ValueError("LLM_API_KEY environment variable not set")
    
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,  # Low temperature for factual output
    })
    
    url = f"{BASE_URL}/chat/completions"
    req = urllib.request.Request(url, data=payload.encode("utf-8"), headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    })
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]


def generate_makeup_content(raw_data: dict, iso_week: str, en_range: str, cn_range: str) -> dict:
    """Generate makeup trends, news, and product rankings using LLM."""
    
    # Prepare raw data summary for LLM
    articles_text = "\n".join(
        f"- [{a['source']}] {a['title']}: {a.get('summary', '')[:200]}"
        for a in raw_data.get("articles", [])[:30]
    )
    
    system_prompt = """You are a beauty industry analyst specializing in makeup trends for the US and Chinese markets. 
You generate structured JSON data for a weekly beauty industry report.

Output ONLY valid JSON (no markdown, no explanation). The JSON must have this structure:
{
  "news": [
    {"region": "CN|US|GLOBAL", "title_cn": "...", "title_en": "...", "brief_cn": "...", "brief_en": "...", "body_cn": "...", "body_en": "...", "tag": "并购|新品|市场|资本|event"}
  ],
  "trends_global": [
    {"title_cn": "...", "title_en": "...", "summary_cn": "...", "summary_en": "...", 
     "chips": [{"platform": "...", "desc": "...", "num": "...", "sub": "...", "tag": "...", "region": "CN|US"}]}
  ],
  "trends_us": [
    {"title_cn": "...", "title_en": "...", "summary_cn": "...", "summary_en": "...",
     "chips": [{"platform": "...", "desc": "...", "num": "...", "sub": "...", "tag": "..."}]}
  ],
  "trends_cn": [
    {"title_cn": "...", "title_en": "...", "summary_cn": "...", "summary_en": "...",
     "chips": [{"platform": "...", "desc": "...", "num": "...", "sub": "...", "tag": "..."}]}
  ],
  "heat_rankings": {
    "us_luxury": [{"rank": 1, "name": "...", "badge": "...", "score": 88, "price": "$XX", "url": "https://...", "features_cn": "...", "features_en": "...", "buzz_cn": "...", "buzz_en": "...", "brand_cn": "...", "brand_en": "..."}],
    "cn_luxury": [{"rank": 1, "name": "...", "badge": "...", "score": 85, "price": "¥XX", "url": "https://...", "features_cn": "...", "features_en": "...", "buzz_cn": "...", "buzz_en": "...", "brand_cn": "...", "brand_en": "..."}]
  },
  "new_products": {
    "us_luxury": [{"rank": 1, "name": "...", "badge": "...", "score": 82, "price": "$XX", "url": "https://...", "features_cn": "...", "features_en": "...", "buzz_cn": "...", "buzz_en": "...", "launch_cn": "...", "launch_en": "..."}],
    "cn_luxury": [{"rank": 1, "name": "...", "badge": "...", "score": 80, "price": "¥XX", "url": "https://...", "features_cn": "...", "features_en": "...", "buzz_cn": "...", "buzz_en": "...", "launch_cn": "...", "launch_en": "..."}]
  }
}

Rules:
- Generate 5-8 news items, 2-3 global trends, 2 US trends, 2 CN trends
- Each trend needs 3-4 signal chips with REAL platform sources (Sephora/TikTok/抖音/小红书/WGSN etc.)
- Heat rankings: 5-10 products per panel (US LUXURY + CN LUXURY)
- New products: 3-7 per panel, only products launched within 4 weeks
- All data must come from the provided articles or well-known public beauty industry knowledge
- Do NOT fabricate specific sales numbers. Use real publicly available data or qualitative descriptions.
- CN fields must be in Chinese, EN fields in English
- Score range: 65-98 (65=Low Confidence, 85=Trending, 90=Viral)
"""

    user_prompt = f"""Generate the makeup section for ISO Week {iso_week} ({en_range}).

Raw data collected from public sources:
{articles_text}

Based on this data and current publicly known beauty industry trends, generate the complete makeup section JSON."""

    print("  Calling LLM for makeup content...")
    response = call_llm(system_prompt, user_prompt)
    
    # Parse JSON from response (handle potential markdown wrapping)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    
    return json.loads(response)


def generate_fragrance_content(raw_data: dict, iso_week: str, en_range: str, cn_range: str) -> dict:
    """Generate fragrance trends, news, and product rankings using LLM."""
    
    articles_text = "\n".join(
        f"- [{a['source']}] {a['title']}: {a.get('summary', '')[:200]}"
        for a in raw_data.get("articles", [])[:30]
    )
    
    system_prompt = """You are a fragrance industry analyst specializing in perfume trends for the US and Chinese markets.
You generate structured JSON data for a weekly fragrance industry report.

Output ONLY valid JSON. Same structure as makeup but for fragrance:
{
  "news": [...],
  "trends_global": [...],
  "trends_us": [...],
  "trends_cn": [...],
  "heat_rankings": {"us_luxury": [...], "cn_luxury": [...]},
  "new_products": {"us_luxury": [...], "cn_luxury": [...]}
}

Rules: Same as makeup but for fragrance products. Focus on perfume trends, fragrance notes, scent families.
- Signal chips must cite real sources (Fragrantica/Sephora/Spate/TikTok etc.)
- Products should be real, publicly available fragrances
- CN fields in Chinese, EN in English"""

    user_prompt = f"""Generate the fragrance section for ISO Week {iso_week} ({en_range}).

Raw data from public sources:
{articles_text}

Based on this data and current publicly known fragrance industry trends, generate the complete fragrance section JSON."""

    print("  Calling LLM for fragrance content...")
    response = call_llm(system_prompt, user_prompt)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    
    return json.loads(response)


def build_canonical_report(makeup: dict, fragrance: dict, iso_week: str, 
                           en_range: str, cn_range: str) -> dict:
    """Build the canonical report.json structure."""
    return {
        "iso_week": iso_week,
        "date_range": en_range,
        "date_range_cn": cn_range,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "makeup": makeup,
        "fragrance": fragrance,
    }


def build_sources(raw_data: dict, makeup: dict, fragrance: dict) -> dict:
    """Build sources.json from collected data and generated content."""
    sources = []
    for s in raw_data.get("sources_fetched", []):
        sources.append({
            "name": s["name"],
            "url": s["url"],
            "type": s["type"],
            "status": "fetched",
        })
    for s in raw_data.get("sources_failed", []):
        sources.append({
            "name": s["name"],
            "url": s["url"],
            "type": "unknown",
            "status": "failed",
            "error": s["error"],
        })
    
    return {
        "schema_version": "2.0.0",
        "total_sources": len(sources),
        "sources": sources,
        "articles": raw_data.get("articles", []),
    }


def build_scoring(makeup: dict, fragrance: dict) -> dict:
    """Build scoring.json from generated product data."""
    all_products = []
    for section in [makeup, fragrance]:
        for panel in ["us_luxury", "cn_luxury"]:
            products = section.get("heat_rankings", {}).get(panel, [])
            for p in products:
                all_products.append({
                    "name": p.get("name", ""),
                    "panel": panel,
                    "score": p.get("score", 0),
                    "has_price": bool(p.get("price")),
                    "has_url": bool(p.get("url")),
                    "has_buzz": bool(p.get("buzz_cn") or p.get("buzz_en")),
                })
    
    return {
        "schema_version": "1.0.0",
        "scoring_formula": "Sales Score (≤50) + Buzz Score (≤50) = Total (≤100)",
        "recomputable": False,  # LLM-generated scores are not recomputable from raw data
        "products": all_products,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def build_manifest(iso_week: str, report_hash: str, sources_hash: str, scoring_hash: str) -> dict:
    """Build manifest.json."""
    return {
        "iso_week": iso_week,
        "schema_version": 3,
        "phase": "auto-generated",
        "canonical_hash": report_hash,
        "sources_hash": sources_hash,
        "scoring_hash": scoring_hash,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator": "build/generate_weekly.py",
        "llm_model": MODEL,
        "note": "Auto-generated from public data sources using LLM synthesis. All product data sourced from public beauty industry information.",
    }


def deterministic_json(obj: dict) -> str:
    """Serialize JSON deterministically."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)


def sha256_of(text: str) -> str:
    """Compute SHA-256 hash of text."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    iso_week = current_iso_week()
    en_range, cn_range, start_date, end_date = iso_week_date_range(iso_week)
    
    print(f"=== Beauty Weekly Content Generation ===")
    print(f"ISO Week: {iso_week}")
    print(f"Date Range: {en_range}")
    print(f"LLM Model: {MODEL}")
    print(f"LLM Base URL: {BASE_URL}")
    print()
    
    # Load raw collected data
    raw_path = ROOT / "data" / "weeks" / iso_week / "raw_collected.json"
    if not raw_path.exists():
        print(f"FATAL: {raw_path} not found. Run build/collect.py first.")
        return 1
    
    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    
    print(f"Loaded raw data: {raw_data.get('total_articles', 0)} articles")
    print()
    
    # Generate content using LLM
    print("--- Generating Makeup Content ---")
    makeup = generate_makeup_content(raw_data, iso_week, en_range, cn_range)
    
    print("\n--- Generating Fragrance Content ---")
    fragrance = generate_fragrance_content(raw_data, iso_week, en_range, cn_range)
    
    # Build canonical four-file set
    print("\n--- Building Canonical Dataset ---")
    report = build_canonical_report(makeup, fragrance, iso_week, en_range, cn_range)
    sources = build_sources(raw_data, makeup, fragrance)
    scoring = build_scoring(makeup, fragrance)
    
    # Compute hashes
    report_json = deterministic_json(report)
    sources_json = deterministic_json(sources)
    scoring_json = deterministic_json(scoring)
    
    report_hash = sha256_of(report_json)
    sources_hash = sha256_of(sources_json)
    scoring_hash = sha256_of(scoring_json)
    
    manifest = build_manifest(iso_week, report_hash, sources_hash, scoring_hash)
    manifest_json = deterministic_json(manifest)
    
    # Write to data/weeks/<iso-week>/
    output_dir = ROOT / "data" / "weeks" / iso_week
    output_dir.mkdir(parents=True, exist_ok=True)
    
    files = {
        "report.json": report_json,
        "sources.json": sources_json,
        "scoring.json": scoring_json,
        "manifest.json": manifest_json,
    }
    
    for fname, content in files.items():
        fpath = output_dir / fname
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  {fname}: {len(content)} bytes")
    
    print(f"\n=== Generation Complete ===")
    print(f"Output dir: {output_dir}")
    print(f"Report hash: {report_hash[:16]}...")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
