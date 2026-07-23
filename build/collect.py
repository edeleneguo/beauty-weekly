#!/usr/bin/env python3
"""collect.py — Auto-collect monthly beauty industry data from public sources.

Zero-input: resolves the previous calendar month, fetches real public data,
and writes raw_collected.json to data/months/<YYYY-MM>/.

Data sources (all public, no API key required):
  - Allure RSS feed (beauty news + trends)
  - BeautyMatter RSS feed (industry news)
  - Sephora bestsellers page (product rankings)
  - Google Trends (beauty-related search trends)
  - Fragrantica new arrivals (fragrance launches)
  - CBNData/36Kr RSS (China market news)

Output: data/months/<YYYY-MM>/raw_collected.json
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.month import (  # noqa: E402
    previous_month_range,
    previous_month_str,
    resolve_month,
)

try:
    from googlenewsdecoder import gnewsdecoder
except ImportError:  # pragma: no cover - dependency is installed in production CI
    gnewsdecoder = None

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

REFERENCE_CONFIG = ROOT / "config" / "reference_sources.json"
CN_DISCOVERY_CONFIG = ROOT / "config" / "cn_new_product_sources.json"

_CN_LAUNCH_CUES = (
    "新品",
    "上市",
    "发布",
    "首发",
    "推出",
    "全新",
    "上新",
)
_CN_CATEGORY_CUES = {
    "makeup": (
        "彩妆",
        "口红",
        "唇膏",
        "唇釉",
        "唇泥",
        "粉底",
        "气垫",
        "遮瑕",
        "粉饼",
        "眼影",
        "腮红",
        "高光",
        "修容",
        "睫毛膏",
        "眼线",
    ),
    "fragrance": (
        "香水",
        "香氛",
        "淡香精",
        "浓香水",
        "古龙水",
        "香精",
    ),
}
_CN_FRAGRANCE_FALSE_POSITIVES = (
    "香水椰",
    "香水柠檬",
    "奶茶",
    "饮料",
    "果茶",
    "家居清洁",
    "衣物清洁",
)
_CN_MAKEUP_STRONG_CUES = tuple(
    cue for cue in _CN_CATEGORY_CUES["makeup"] if cue not in {"高光", "修容"}
)


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta" or self.description:
            return
        values = {str(key).casefold(): value or "" for key, value in attrs}
        marker = (values.get("name") or values.get("property")).casefold()
        if marker in {"description", "og:description", "twitter:description"}:
            self.description = values.get("content", "").strip()


def fetch_url(url: str) -> str:
    """Fetch URL content with timeout and user agent."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _decode_google_news_url(url: str) -> str | None:
    if urlparse(url).netloc.casefold() != "news.google.com":
        return url
    if gnewsdecoder is None:
        return None
    decoded = gnewsdecoder(url, interval=0)
    if not isinstance(decoded, dict) or not decoded.get("status"):
        return None
    direct_url = str(decoded.get("decoded_url", "")).strip()
    if not direct_url or urlparse(direct_url).netloc.casefold() == "news.google.com":
        return None
    return direct_url


def _enrich_article_direct_url(article: dict) -> dict:
    original_url = str(article.get("url", ""))
    direct_url = _decode_google_news_url(original_url)
    if not direct_url:
        article["direct_url_status"] = "decode_failed"
        return article

    if direct_url != original_url:
        article["aggregator_url"] = original_url
        article["url"] = direct_url
    article["direct_url_status"] = "direct"

    try:
        parser = _MetadataParser()
        parser.feed(fetch_url(direct_url))
        if parser.description:
            article["summary"] = parser.description[:1200]
        article["page_fetch_status"] = "fetched"
    except Exception as exc:
        article["page_fetch_status"] = "failed"
        article["page_fetch_error"] = str(exc)[:200]
    return article


def _enrich_discovery_articles(articles: list[dict]) -> list[dict]:
    if not articles:
        return []
    enriched: list[dict | None] = [None] * len(articles)
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(_enrich_article_direct_url, dict(article)): index
            for index, article in enumerate(articles)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                enriched[index] = future.result()
            except Exception as exc:
                fallback = dict(articles[index])
                fallback["direct_url_status"] = "decode_failed"
                fallback["direct_url_error"] = str(exc)[:200]
                enriched[index] = fallback
    return [article for article in enriched if article is not None]


def parse_rss(
    xml_text: str, source_name: str, *, market: str = "GLOBAL", reference_type: str = ""
) -> list[dict]:
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
                    "market": market,
                    "reference_type": reference_type,
                })
    except ElementTree.ParseError:
        pass
    return articles[:20]  # Limit to 20 articles per source


def _load_main_references() -> list[dict]:
    with open(REFERENCE_CONFIG, encoding="utf-8") as f:
        config = json.load(f)
    return config["main_references"]


def _load_cn_discovery_config() -> dict:
    with open(CN_DISCOVERY_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _month_window(month: str) -> tuple[str, str, str]:
    year, month_number = (int(part) for part in month.split("-"))
    start, end = previous_month_range(year, month_number)
    return start.isoformat(), end.isoformat(), (end + timedelta(days=1)).isoformat()


def _news_search_url(query: str, market: str, month: str | None = None) -> str:
    if month:
        start, _end, exclusive_end = _month_window(month)
        query = f"{query} after:{start} before:{exclusive_end}"
    if market == "US":
        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    else:
        params = {"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def _reference_search_url(reference: dict, month: str | None = None) -> str:
    query = f'{reference["name"]} (美妆 OR 护肤 OR 香水 OR 彩妆)'
    if reference["market"] == "US":
        query = f'{reference["name"]} (beauty OR makeup OR fragrance OR skincare)'
    return _news_search_url(query, reference["market"], month)


def _format_discovery_query(query: dict, month: str) -> str:
    year, month_number = (int(part) for part in month.split("-"))
    return query["query"].format(year=year, month_number=month_number)


def _fetch_main_reference(reference: dict, month: str | None = None) -> tuple[dict, list[dict]]:
    """Search one mandatory reference and return its audit record plus results."""
    url = _reference_search_url(reference, month)
    content = fetch_url(url)
    articles = parse_rss(
        content,
        reference["name"],
        market=reference["market"],
        reference_type=reference["type"],
    )
    if reference.get("category"):
        for article in articles:
            article["category"] = reference["category"]
            article["discovery_stage"] = "brand_search"
    return (
        {
            "name": reference["name"],
            "market": reference["market"],
            "reference_type": reference["type"],
            "type": "search_rss",
            "articles_count": len(articles),
            "url": url,
            "mandatory_search": True,
        },
        articles,
    )


def _fetch_cn_discovery_query(query: dict, category: str, month: str) -> tuple[dict, list[dict]]:
    query_text = _format_discovery_query(query, month)
    url = _news_search_url(query_text, "CN", month)
    content = fetch_url(url)
    articles = parse_rss(
        content,
        query["name"],
        market="CN",
        reference_type=f"{category}_new_product_discovery",
    )
    articles = [
        article for article in articles if _is_cn_new_product_article(article, category)
    ]
    articles = _enrich_discovery_articles(articles)
    for article in articles:
        article["category"] = category
        article["discovery_stage"] = "broad"
    return (
        {
            "name": query["name"],
            "category": category,
            "market": "CN",
            "type": "new_product_discovery",
            "articles_count": len(articles),
            "url": url,
        },
        articles,
    )


def _is_cn_new_product_article(article: dict, category: str) -> bool:
    combined = " ".join(
        str(article.get(field, "")).casefold() for field in ("title", "summary")
    )
    if not any(cue in combined for cue in _CN_LAUNCH_CUES):
        return False
    if not any(cue in combined for cue in _CN_CATEGORY_CUES[category]):
        return False
    if category == "makeup" and not any(cue in combined for cue in _CN_MAKEUP_STRONG_CUES):
        return False
    return not (
        category == "fragrance"
        and any(cue in combined for cue in _CN_FRAGRANCE_FALSE_POSITIVES)
    )


def search_product_evidence(
    product_name: str,
    category: str,
    month: str,
) -> tuple[dict, list[dict]]:
    """Run a candidate-specific CN evidence search for the target month."""
    category_terms = "彩妆 美妆" if category == "makeup" else "香水 香氛"
    query = f'"{product_name}" ({category_terms}) (新品 OR 上市 OR 发布 OR 首发)'
    url = _news_search_url(query, "CN", month)
    content = fetch_url(url)
    articles = parse_rss(
        content,
        f"candidate:{product_name}",
        market="CN",
        reference_type="candidate_verification",
    )
    articles = _enrich_discovery_articles(articles)
    for article in articles:
        article["category"] = category
        article["discovery_stage"] = "candidate_verification"
        article["candidate_name"] = product_name
    return (
        {
            "product_name": product_name,
            "category": category,
            "market": "CN",
            "type": "candidate_verification",
            "articles_count": len(articles),
            "url": url,
        },
        articles,
    )


def _dedupe_articles(articles: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen_urls: set[str] = set()
    for article in articles:
        url = article.get("url", "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(article)
    return unique


def collect_all(target_month: str | None = None) -> dict:
    """Collect data from all configured sources."""
    month = resolve_month(target_month or previous_month_str())
    window_start, window_end, _exclusive_end = _month_window(month)
    today = date.today().isoformat()

    result = {
        "month": month,
        "window_start": window_start,
        "window_end": window_end,
        "collected_at": datetime.utcnow().isoformat() + "Z",
        "date": today,
        "sources_fetched": [],
        "sources_failed": [],
        "main_reference_audit": [],
        "cn_new_product_discovery_audit": [],
        "candidate_evidence_audit": [],
        "articles": [],
        "products": [],
        "trends": [],
    }

    for name, config in SOURCES.items():
        try:
            print(f"  Fetching {name}...")
            content = fetch_url(config["url"])

            if config["type"] == "rss":
                articles = parse_rss(
                    content,
                    name,
                    market=config["market"],
                    reference_type=config["category"],
                )
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

    # Main references are mandatory searches, not a publication whitelist.
    # Search every entry on every run and preserve failures in the audit trail.
    references = _load_main_references()
    print(f"  Searching {len(references)} mandatory main references...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(_fetch_main_reference, ref, month): ref for ref in references
        }
        for future in as_completed(future_map):
            ref = future_map[future]
            try:
                audit, articles = future.result()
                result["main_reference_audit"].append(audit)
                result["articles"].extend(articles)
            except Exception as exc:
                result["main_reference_audit"].append(
                    {
                        "name": ref["name"],
                        "market": ref["market"],
                        "reference_type": ref["type"],
                        "type": "search_rss",
                        "articles_count": 0,
                        "url": _reference_search_url(ref, month),
                        "mandatory_search": True,
                        "error": str(exc)[:200],
                    }
                )

    discovery_config = _load_cn_discovery_config()
    discovery_jobs = [
        (category, query)
        for category, queries in discovery_config["discovery_queries"].items()
        for query in queries
    ]
    print(f"  Searching {len(discovery_jobs)} dedicated CN new-product queries...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(_fetch_cn_discovery_query, query, category, month): (
                category,
                query,
            )
            for category, query in discovery_jobs
        }
        for future in as_completed(future_map):
            category, query = future_map[future]
            try:
                audit, articles = future.result()
                result["cn_new_product_discovery_audit"].append(audit)
                result["articles"].extend(articles)
            except Exception as exc:
                result["cn_new_product_discovery_audit"].append(
                    {
                        "name": query["name"],
                        "category": category,
                        "market": "CN",
                        "type": "new_product_discovery",
                        "articles_count": 0,
                        "url": _news_search_url(_format_discovery_query(query, month), "CN", month),
                        "error": str(exc)[:200],
                    }
                )

    result["main_reference_audit"].sort(key=lambda item: (item["market"], item["name"]))
    brand_indexes = [
        index
        for index, article in enumerate(result["articles"])
        if article.get("discovery_stage") == "brand_search"
    ][:80]
    enriched_brands = _enrich_discovery_articles(
        [result["articles"][index] for index in brand_indexes]
    )
    for index, article in zip(brand_indexes, enriched_brands):
        result["articles"][index] = article

    result["cn_new_product_discovery_audit"].sort(
        key=lambda item: (item["category"], item["name"])
    )
    result["main_references_searched"] = len(result["main_reference_audit"])
    result["main_references_with_results"] = sum(
        item["articles_count"] > 0 for item in result["main_reference_audit"]
    )

    result["articles"] = _dedupe_articles(result["articles"])
    result["total_articles"] = len(result["articles"])
    result["total_sources_ok"] = len(result["sources_fetched"])
    result["total_sources_fail"] = len(result["sources_failed"])

    return result


def main() -> int:
    month = resolve_month(os.environ.get("BEAUTY_MONTHLY_MONTH") or previous_month_str())
    print("=== Beauty Monthly Data Collection ===")
    print(f"Month: {month}")
    print(f"Date: {date.today().isoformat()}")
    print()

    data = collect_all(month)

    # Write to data/months/<YYYY-MM>/raw_collected.json
    output_dir = ROOT / "data" / "months" / month
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
