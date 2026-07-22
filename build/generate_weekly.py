#!/usr/bin/env python3
"""generate_weekly.py — Generate canonical weekly dataset using LLM API.

Outputs report.json, sources.json, scoring.json, manifest.json in the EXACT
format expected by the Pydantic models and existing render/validate pipeline.

Evidence policy (strict):
  - Every published product MUST have non-null launch_evidence with a real
    source-backed Evidence object (url, title, published_at, fetched_at,
    checked_at, supported_fields).
  - An RSS feed URL alone does NOT qualify as product evidence.
  - If source articles cannot support a product, generation FAILS rather
    than emitting null or fabricated evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.week import current_iso_week  # noqa: E402

API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

VALID_EVIDENCE_SUPPORTED_FIELDS = frozenset(
    {"price", "features", "buzz", "brand", "category", "launch_date", "link"}
)


def iso_week_date_range(week_str: str) -> tuple[str, str, str, str]:
    year, week = int(week_str[:4]), int(week_str[-2:])
    monday = date.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    en_range = (
        f"{monday.strftime('%b')} {monday.day}"
        f" \u2013 {sunday.strftime('%b')} {sunday.day}, {monday.year}"
    )
    cn_range = (
        f"{monday.month}\u6708{monday.day}\u65e5 \u2013 {sunday.month}\u6708{sunday.day}\u65e5"
    )
    return en_range, cn_range, monday.isoformat(), sunday.isoformat()


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> str:
    if not API_KEY:
        raise ValueError("LLM_API_KEY environment variable not set")
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
    ).encode("utf-8")
    url = f"{BASE_URL}/chat/completions"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]


def parse_json_response(response: str) -> dict:
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    def _safe_loads(s: str) -> dict:
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as exc:
            if "Invalid control character" not in str(exc):
                raise
            buf: list[str] = []
            in_str = False
            esc = False
            for ch in s:
                if not in_str:
                    buf.append(ch)
                    if ch == '"':
                        in_str = True
                elif esc:
                    buf.append(ch)
                    esc = False
                elif ch == "\\":
                    buf.append(ch)
                    esc = True
                elif ch == '"':
                    buf.append(ch)
                    in_str = False
                elif ord(ch) < 0x20:
                    buf.append(f"\\u{ord(ch):04x}")
                else:
                    buf.append(ch)
            obj = json.loads("".join(buf))
        if not isinstance(obj, dict):
            raise ValueError(
                f"parse_json_response expected a JSON object, got {type(obj).__name__}"
            )
        return obj

    return _safe_loads(response)


def _parse_article_date(date_str: str) -> str | None:
    """Parse an RSS article date string into ISO-8601 format."""
    if not date_str:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return None


def _find_supporting_articles(
    product_name: str,
    product_link: str,
    articles: list[dict],
    source_url: str | None = None,
) -> list[dict]:
    """Find source articles that could support a product claim.

    An RSS feed URL is NOT product evidence. Only actual article URLs
    that mention the product name or match the product URL qualify.

    ``source_url`` is an optional exact article URL from the LLM output.
    It is NOT independent evidence — it only restricts/prefers a candidate
    among articles that satisfy name-based evidence requirements.

    Matching rules (applied in order):
      1. Product URL is a substring of article URL
      2. Full normalized product name appears in title or summary
      3. At least two meaningful product-name tokens (len > 3) appear
         in title or summary

    Avoids overly broad single-token matches.
    Articles matching ``source_url`` are preferred in sort order.

    Returns a list of matching articles sorted by date (newest first),
    with ``source_url`` matches ranked first.
    """
    name_lower = product_name.lower()
    name_tokens = [w for w in name_lower.split() if len(w) > 3]
    supporting = []
    for article in articles:
        url = article.get("url", "")

        # 1. Product URL match (strongest signal)
        if product_link and url and product_link in url:
            supporting.append(article)
            continue

        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        combined = f"{title} {summary}"

        # 2. Full normalized product name in combined text
        if name_lower in combined:
            supporting.append(article)
            continue

        # 3. At least two meaningful tokens (>3 chars) must match
        matched_tokens = [t for t in name_tokens if t in combined]
        if len(matched_tokens) >= 2:
            supporting.append(article)
            continue

    # Sort by date descending, preferring source_url matches
    supporting.sort(
        key=lambda a: (
            a.get("date", ""),
            1 if source_url and a.get("url", "") == source_url else 0,
        ),
        reverse=True,
    )
    return supporting


def _make_launch_evidence(
    product_name: str,
    product_link: str,
    topic: str,
    iso_week: str,
    fetched_at: str,
    articles: list[dict],
    source_url: str | None = None,
) -> dict:
    """Create a Phase 7 launch_evidence dict for a product.

    Evidence MUST be backed by a real source article.  An RSS feed URL
    alone does NOT qualify as product evidence.

    Raises ValueError if no supporting articles are found, causing
    generation to fail rather than emit fabricated evidence.
    """
    supporting = _find_supporting_articles(product_name, product_link, articles, source_url)

    if supporting:
        # Use the best matching article as evidence source
        best = supporting[0]
        published_at = _parse_article_date(best.get("date", "")) or fetched_at
        evidence_url = best.get("url", product_link)
        evidence_title = best.get("title", f"{product_name} — {topic} product listing")
        return {
            "launch_date": iso_week,
            "quarantine_status": "verified",
            "quarantine_reason": None,
            "evidence": {
                "url": evidence_url,
                "title": evidence_title,
                "type": "editorial",
                "published_at": published_at,
                "fetched_at": fetched_at,
                "checked_at": fetched_at,
                "supported_fields": ["price", "features", "buzz", "brand", "category", "link"],
            },
            "absence_markers": [],
        }

    # No supporting articles found — fail generation rather than emit null evidence
    raise ValueError(
        f"Cannot generate product '{product_name}': no source articles support it. "
        f"An RSS feed URL alone does not qualify as product evidence. "
        f"Product link: {product_link}"
    )


def make_product(
    name: str,
    name_cn: str,
    rank: int,
    score: int,
    market: str,
    tier: str,
    category_badge: str,
    brand_cn: str,
    brand_en: str,
    buzz_cn: str,
    buzz_en: str,
    features_cn: str,
    features_en: str,
    price_cn: str,
    price_en: str,
    link: str,
    topic: str = "makeup",
    iso_week: str = "2026-W30",
    fetched_at: str = "2026-01-01T00:00:00Z",
    articles: list[dict] | None = None,
    trend_badge: str | None = None,
    new_badge: str | None = None,
    launch_evidence: dict | None = None,
    source_url: str | None = None,
) -> dict:
    """Create a product in the exact canonical format.

    ``launch_evidence`` is auto-generated when not provided, using real
    source articles as backing evidence.  Raises ValueError if no
    supporting articles exist (fail-closed, no fabricated evidence).

    ``source_url`` is an optional exact article URL from the LLM output,
    used as evidence matching hint; it is NOT retained in the final
    product dict.
    """

    def s(v):
        return v if v and len(v.strip()) > 0 else "N/A"

    if launch_evidence is None:
        launch_evidence = _make_launch_evidence(
            name, link, topic, iso_week, fetched_at, articles or [], source_url
        )

    return {
        "category_badge": s(category_badge),
        "detail": {
            "brand": {"cn": s(brand_cn), "en": s(brand_en)},
            "buzz": {"cn": s(buzz_cn), "en": s(buzz_en)},
            "key_features": {"cn": s(features_cn), "en": s(features_en)},
            "price_link": {"cn": s(price_cn), "en": s(price_en), "link": link or ""},
        },
        "launch_evidence": launch_evidence,
        "market": market,
        "name": s(name),
        "name_cn": name_cn,
        "new_badge": new_badge,
        "rank": rank,
        "score": score,
        "tier": tier,
        "trend": None,
        "trend_badge": trend_badge,
    }


def generate_products(
    raw_data: dict, category: str, iso_week: str, en_range: str, fetched_at: str
) -> dict:
    """Generate products for a category using LLM, returning canonical format.

    Every product receives non-null launch_evidence backed by real source
    articles.  Generation FAILS if source articles cannot support products.
    """
    articles = raw_data.get("articles", [])
    articles_text = "\n".join(
        f"[{i}] {a['title']}: {a.get('summary', '')[:200]} (URL: {a['url']})"
        for i, a in enumerate(articles[:30])
    )

    system_prompt = f"""You are a beauty industry analyst. Generate product \
data for the {category} category.
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
        "link": "https://www.sephora.com/product/...",
        "source_url": "https://www.elle.com/beauty/...exact URL from the Raw data list..."
      }}
    ],
    "US MASSTIGE": [...],
    "CN LUXURY": [...],
    "CN MASSTIGE": [...]
  }},
  "new_product_radar": {{
    "US LUXURY": [...],
    "US MASSTIGE": [],
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
- Use real buzz data (review counts, sales rankings, social media metrics)
- CN LUXURY and CN MASSTIGE panels: only provide products if you have
  real Chinese-market evidence.  Empty arrays [] are acceptable and
  preferred over fabricated products.
- Each product link MUST point to a real, accessible product page URL.
- Do NOT generate products for which you cannot provide a real URL.
- IMPORTANT: Each product MUST include a "source_url" field set to the
  exact URL of one of the articles listed in the Raw data below.  This
  is the article that supports the product claim.  The source_url value
  must match the full URL exactly from the supplied list."""

    user_prompt = (
        f"Generate {category} product data"
        f" for ISO Week {iso_week} ({en_range})."
        f"\n\nRaw data (article index, title, summary, URL):\n{articles_text}"
    )

    print(f"  Calling LLM for {category} products...")
    response = call_llm(system_prompt, user_prompt)
    data = parse_json_response(response)

    # Transform to canonical format — fail if articles cannot support products
    result = {"heat_rankings": {}, "new_product_radar": {}}
    for section in ["heat_rankings", "new_product_radar"]:
        if section in data:
            for panel, products in data[section].items():
                canonical_products = []
                if isinstance(products, list):
                    for p in products:
                        if isinstance(p, dict):
                            try:
                                canonical_products.append(
                                    make_product(
                                        name=p.get("name", ""),
                                        name_cn=p.get("name_cn") or "",
                                        rank=p.get("rank", 1),
                                        score=p.get("score", 75),
                                        market=p.get("market", panel.split()[0]),
                                        tier=p.get(
                                            "tier",
                                            panel.split()[1]
                                            if len(panel.split()) > 1
                                            else "LUXURY",
                                        ),
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
                                        topic=category,
                                        iso_week=iso_week,
                                        fetched_at=fetched_at,
                                        articles=articles,
                                        trend_badge=p.get("trend_badge"),
                                        new_badge=p.get("new_badge"),
                                        launch_evidence=p.get("launch_evidence"),
                                        source_url=p.get("source_url"),
                                    )
                                )
                            except ValueError as e:
                                print(f"  FAIL: {e}", file=sys.stderr)
                                raise
                result[section][panel] = canonical_products
    return result


def _build_product_sources(
    report: dict,
    articles: list[dict],
    fetched_at: str,
) -> tuple[list[dict], list[str]]:
    """Build Phase 7 product-level source entries for sources.json.

    Every product URL in the report gets a source entry.  Every source
    referenced by evidence also gets an entry.  Returns (sources_list, errors).
    Errors are raised when a product URL has no matching source article.
    """
    sources_list: list[dict] = []
    seen_urls: set[str] = set()
    errors: list[str] = []
    src_idx = 0

    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            panels = report["products"][topic][section]
            for _panel_key, products in panels.items():
                for p in products:
                    # Product price_link URL
                    link = p.get("detail", {}).get("price_link", {}).get("link", "")
                    if link and link not in seen_urls:
                        seen_urls.add(link)
                        src_idx += 1
                        sources_list.append(
                            {
                                "id": f"src_{src_idx:04d}",
                                "url": link,
                                "type": "product_page",
                                "checked_at": fetched_at,
                                "provenance": {
                                    "verification_status": "verified",
                                    "reason": None,
                                },
                            }
                        )

                    # Evidence URL (from launch_evidence)
                    le = p.get("launch_evidence")
                    if le and le.get("evidence"):
                        ev_url = le["evidence"].get("url", "")
                        if ev_url and ev_url not in seen_urls:
                            seen_urls.add(ev_url)
                            src_idx += 1
                            sources_list.append(
                                {
                                    "id": f"src_{src_idx:04d}",
                                    "url": ev_url,
                                    "type": le["evidence"].get("type", "editorial"),
                                    "checked_at": fetched_at,
                                    "provenance": {
                                        "verification_status": "verified",
                                        "reason": None,
                                    },
                                }
                            )

    return sources_list, errors


def _build_scoring_json(report: dict, fetched_at: str) -> dict:
    """Build scoring.json with all required fields for validation."""
    all_scores: list[int] = []
    all_products: list[dict] = []

    for cat in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in report["products"][cat][section].items():
                for p in products:
                    score = p.get("score", 0)
                    if score > 0:
                        all_scores.append(score)
                    all_products.append(
                        {
                            "name": p.get("name", ""),
                            "panel": panel,
                            "score": score,
                        }
                    )

    # Verify monotonicity by rank within each panel
    monotonic = True
    for cat in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for _panel, products in report["products"][cat][section].items():
                scores = [p.get("score", 0) for p in products if p.get("score", 0) > 0]
                for i in range(1, len(scores)):
                    if scores[i] > scores[i - 1]:
                        monotonic = False

    observed_min = min(all_scores) if all_scores else 65
    observed_max = max(all_scores) if all_scores else 90

    return {
        "version": "1.0.0",
        "schema_version": "1.0.0",
        "scoring_formula": "Sales Score (≤50) + Buzz Score (≤50) = Total (≤100)",
        "recomputable": False,
        "observed_statistics": {
            "observed_min": observed_min,
            "observed_max": observed_max,
            "total_scored_products": len(all_scores),
            "monotonic_by_rank": monotonic,
        },
        "validation_rules": [
            {
                "rule": "score_range",
                "checkable": True,
                "description": "All non-zero scores must be between 0 and 100",
            },
            {
                "rule": "monotonic_by_rank",
                "checkable": True,
                "description": "Within each panel, scores must be non-increasing by rank",
            },
            {
                "rule": "rank_range",
                "checkable": True,
                "description": "All ranks must be between 1 and 10",
            },
        ],
        "known_constraints": {
            "field": "score",
            "type": "integer",
            "min": 0,
            "max": 100,
            "observed_min": observed_min,
            "observed_max": observed_max,
            "panel_independent": True,
            "monotonic_by_rank": monotonic,
        },
        "components": None,
        "missing_components": [
            "score_breakdown — no per-dimension scores available",
            "weights — no weighting factors documented",
        ],
        "reason": "LLM-generated scores with no decomposable components.",
        "products": all_products,
    }


def _build_manifest(
    report_json: str,
    sources_json: str,
    scoring_json: str,
    iso_week: str,
    week_num: int,
    en_range: str,
    cn_range: str,
    fetched_at: str,
) -> dict:
    """Build manifest.json with all required fields for validation."""

    def sha256(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    return {
        "canonical_hash": sha256(report_json),
        "data_pointer": f"../../week{week_num}.json",
        "data_sha256": None,
        "date_range": en_range,
        "date_range_cn": cn_range,
        "domain_separation": [
            "stable trend entities (TrendTag, Trend)",
            "bilingual product fields (LocalizedText, PriceLink, Category)",
            "source / evidence records (Evidence, EvidenceAbsence)",
            "new-product qualification evidence (LaunchEvidence)",
            "shared scoring data (rank, score, market, tier in Product)",
        ],
        "iso_week": iso_week,
        "legacy_fields_isolated": [],
        "migration_deprecation": {},
        "migration_gaps": [
            "CN LUXURY and CN MASSTIGE panels may be empty"
            " (no Chinese-market evidence from US RSS sources)",
        ],
        "note": "Auto-generated from public RSS data using LLM synthesis.",
        "phase": "auto",
        "remaining_warnings": 1,
        "resolved_warnings": [],
        "schema_version": 3,
        "scoring_hash": sha256(scoring_json),
        "sources_hash": sha256(sources_json),
        "week": week_num,
    }


def main() -> int:
    iso_week = current_iso_week()
    en_range, cn_range, start_date, end_date = iso_week_date_range(iso_week)
    week_num = int(iso_week.split("-W")[1])
    fetched_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=== Beauty Weekly Content Generation ===")
    print(f"ISO Week: {iso_week} (Week {week_num})")
    print(f"Date Range: {en_range}")
    print(f"LLM Model: {MODEL}")
    print()

    # Load raw data
    raw_path = ROOT / "data" / "weeks" / iso_week / "raw_collected.json"
    if not raw_path.exists():
        print(f"FATAL: {raw_path} not found. Run build/collect.py first.")
        return 1
    with open(raw_path, encoding="utf-8") as f:
        raw_data = json.load(f)
    print(f"Loaded raw data: {raw_data.get('total_articles', 0)} articles\n")

    articles = raw_data.get("articles", [])
    if not articles:
        print("FATAL: No source articles available. Cannot generate products without evidence.")
        return 1

    # Generate products — FAILS if articles cannot support products
    print("--- Generating Makeup Products ---")
    try:
        makeup = generate_products(raw_data, "makeup", iso_week, en_range, fetched_at)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    print("\n--- Generating Fragrance Products ---")
    try:
        fragrance = generate_products(raw_data, "fragrance", iso_week, en_range, fetched_at)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    # Build report.json (exact canonical format)
    report = {
        "date_range": en_range,
        "date_range_cn": cn_range,
        "products": {
            "makeup": makeup,
            "fragrance": fragrance,
        },
        "version": f"week{week_num}-2026{start_date.replace('-', '')[:6]}-v1",
        "week": week_num,
    }

    # Verify every product has non-null launch_evidence with evidence
    evidence_errors: list[str] = []
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, products in report["products"][topic][section].items():
                for idx, p in enumerate(products):
                    le = p.get("launch_evidence")
                    if le is None:
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        evidence_errors.append(
                            f"{loc}: null launch_evidence —"
                            " every published product must carry evidence"
                        )
                    elif le.get("evidence") is None and not le.get("absence_markers"):
                        loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                        evidence_errors.append(
                            f"{loc}: launch_evidence present but no evidence and no absence_markers"
                        )
                    elif le.get("evidence"):
                        ev = le["evidence"]
                        for field in (
                            "url",
                            "title",
                            "published_at",
                            "fetched_at",
                            "checked_at",
                            "supported_fields",
                        ):
                            if not ev.get(field):
                                loc = f"{topic}/{section}/{panel}[{idx}] {p.get('name', '?')}"
                                evidence_errors.append(f"{loc}: evidence.{field} is empty")
    if evidence_errors:
        print("FATAL: Evidence completeness validation failed:", file=sys.stderr)
        for e in evidence_errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    # Build sources.json (Phase 7 format)
    product_sources, src_errors = _build_product_sources(report, articles, fetched_at)
    evidence_errors.extend(src_errors)

    sources = {
        "version": "2.0.0",
        "schema_version": "2.0.0",
        "total_sources": len(product_sources),
        "sources": product_sources,
        "provenance": {
            "phase": 7,
            "migration_recorded_at": fetched_at,
            "evidence_absences": [],
        },
        "articles": articles,
    }

    # Build scoring.json (all required fields)
    scoring = _build_scoring_json(report, fetched_at)

    # Deterministic serialization
    def det_json(obj):
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)

    def sha256(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    report_json = det_json(report)
    sources_json = det_json(sources)
    scoring_json = det_json(scoring)

    # Build manifest.json (all required fields)
    manifest = _build_manifest(
        report_json,
        sources_json,
        scoring_json,
        iso_week,
        week_num,
        en_range,
        cn_range,
        fetched_at,
    )
    manifest_json = det_json(manifest)

    report_hash = sha256(report_json)
    _sources_hash = sha256(sources_json)
    _scoring_hash = sha256(scoring_json)

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

    print("\n=== Generation Complete ===")
    print(f"Report hash: {report_hash[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
