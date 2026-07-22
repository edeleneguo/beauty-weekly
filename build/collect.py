#!/usr/bin/env python3
"""collect.py — Auto-collect raw beauty industry data from public sources.

Zero-input: auto-calculates current ISO week, fetches real public data,
and writes raw_collected.json to data/weeks/<iso-week>/.

Data sources (all public, no API key required):
  - Allure RSS feed (beauty news + trends)
  - BeautyMatter RSS feed (industry news)
  - Sephora bestsellers page (product rankings)
  - Google Trends (beauty-related search trends)
  - Fragrantica new arrivals (fragrance launches)
  - CBNData/36Kr RSS (China market news)

Output: data/weeks/<iso-week>/raw_collected.json
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.week import current_iso_week  # noqa: E402

# --- Configuration ---
TIMEOUT = 15  # seconds per request
USER_AGENT = "BeautyWeeklyBot/1.0 (automated data collection)"

SOURCES = {
    "elle_beauty": {
        "url": "https://www.elle.com/rss/beauty",
        "type": "rss",
        "market": "US",
        "category": "makeup",
    },
    "harpers_bazaar_beauty": {
        "url": "https://www.harpersbazaar.com/rss/beauty",
        "type": "rss",
        "market": "US",
        "category": "makeup",
    },
    "glossy": {
        "url": "https://www.glossy.co/feed",
        "type": "rss",
        "market": "GLOBAL",
        "category": "industry",
    },
    "now_smell_this": {
        "url": "https://www.nstperfume.com/feed/",
        "type": "rss",
        "market": "GLOBAL",
        "category": "fragrance",
    },
    "cosmopolitan_beauty": {
        "url": "https://www.cosmopolitan.com/rss/beauty",
        "type": "rss",
        "market": "US",
        "category": "makeup",
    },
}


def fetch_url(url: str) -> str:
    """Fetch URL content with timeout and user agent."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_text: str, source_name: str) -> list[dict]:
    """Parse RSS XML and extract articles."""
    articles = []
    try:
        root = ElementTree.fromstring(xml_text)
        # RSS 2.0 format
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            if title and link:
                articles.append({
                    "source": source_name,
                    "title": title.strip(),
                    "url": link.strip(),
                    "date": pub_date.strip(),
                    "summary": description.strip()[:500] if description else "",
                })
    except ElementTree.ParseError:
        pass
    return articles[:20]  # Limit to 20 articles per source


def collect_all() -> dict:
    """Collect data from all configured sources."""
    iso_week = current_iso_week()
    today = date.today().isoformat()

    result = {
        "iso_week": iso_week,
        "collected_at": datetime.utcnow().isoformat() + "Z",
        "date": today,
        "sources_fetched": [],
        "sources_failed": [],
        "articles": [],
        "products": [],
        "trends": [],
    }

    for name, config in SOURCES.items():
        try:
            print(f"  Fetching {name}...")
            content = fetch_url(config["url"])

            if config["type"] == "rss":
                articles = parse_rss(content, name)
                result["articles"].extend(articles)
                result["sources_fetched"].append({
                    "name": name,
                    "type": "rss",
                    "articles_count": len(articles),
                    "url": config["url"],
                })
                print(f"    ✓ {len(articles)} articles")
            elif config["type"] == "scrape":
                # For scrape sources, store raw HTML for LLM processing
                result["sources_fetched"].append({
                    "name": name,
                    "type": "scrape",
                    "content_length": len(content),
                    "url": config["url"],
                })
                result["articles"].append({
                    "source": name,
                    "title": f"{name} page content",
                    "url": config["url"],
                    "date": today,
                    "summary": content[:2000],  # First 2000 chars for LLM
                })
                print(f"    ✓ {len(content)} chars scraped")
            elif config["type"] == "api":
                result["sources_fetched"].append({
                    "name": name,
                    "type": "api",
                    "content_length": len(content),
                    "url": config["url"],
                })
                result["articles"].append({
                    "source": name,
                    "title": f"{name} API response",
                    "url": config["url"],
                    "date": today,
                    "summary": content[:2000],
                })
                print(f"    ✓ {len(content)} chars from API")

        except Exception as e:
            result["sources_failed"].append({
                "name": name,
                "error": str(e)[:200],
                "url": config["url"],
            })
            print(f"    ✗ FAILED: {e}")

    result["total_articles"] = len(result["articles"])
    result["total_sources_ok"] = len(result["sources_fetched"])
    result["total_sources_fail"] = len(result["sources_failed"])

    return result


def main() -> int:
    iso_week = current_iso_week()
    print("=== Beauty Weekly Data Collection ===")
    print(f"ISO Week: {iso_week}")
    print(f"Date: {date.today().isoformat()}")
    print()

    data = collect_all()

    # Write to data/weeks/<iso-week>/raw_collected.json
    output_dir = ROOT / "data" / "weeks" / iso_week
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "raw_collected.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print()
    print("=== Collection Complete ===")
    print(f"Output: {output_path}")
    print(f"Articles: {data['total_articles']}")
    print(f"Sources OK: {data['total_sources_ok']}")
    print(f"Sources Failed: {data['total_sources_fail']}")

    # Fail if no data collected at all
    if data["total_articles"] == 0:
        print("FATAL: No data collected from any source.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
