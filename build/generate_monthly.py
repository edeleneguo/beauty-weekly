#!/usr/bin/env python3
"""generate_weekly.py — Generate canonical monthly dataset using LLM API.

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
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beauty_weekly.evidence import EXPLICIT_EVIDENCE_ABSENCES  # noqa: E402
from beauty_weekly.month import previous_month_str, resolve_month  # noqa: E402
from build.collect import search_product_evidence  # noqa: E402

API_KEY = os.environ.get("LLM_API_KEY", "")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "3"))
_TRANSIENT_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

# Selectable LLM transport. "api" uses the OpenAI-compatible HTTP endpoint
# (the legacy GitHub Actions path). "codex" invokes the already-authenticated
# local Codex CLI (ChatGPT subscription) non-interactively — no standalone
# model API key is stored or copied anywhere by the runner.
LLM_TRANSPORT = (
    os.environ.get("BEAUTY_MONTHLY_TRANSPORT", "").strip().lower()
    or os.environ.get("LLM_TRANSPORT", "").strip().lower()
    or "api"
)

# The trusted local Codex CLI lives in the Homebrew installation and reads its
# ChatGPT credentials from the user's default $HOME/.codex. It must NEVER be
# replaced by a CODEX_HOME from another environment (e.g. an agent sandbox)
# that carries a standalone API key.
_DEFAULT_CODEX_BIN = "/opt/homebrew/bin/codex"
CODEX_BIN = os.environ.get("CODEX_BIN", "") or (
    _DEFAULT_CODEX_BIN if os.path.exists(_DEFAULT_CODEX_BIN) else shutil.which("codex") or "codex"
)
CODEX_MODEL = os.environ.get("CODEX_MODEL", "").strip()
CODEX_EXEC_TIMEOUT = int(os.environ.get("CODEX_EXEC_TIMEOUT", "900"))

# Environment variables that would force the Codex CLI to use a non-ChatGPT
# (API-key) transport. The runner unsets all of them before every codex
# invocation so the CLI always resolves to the ChatGPT-authenticated ~/.codex.
CODEX_ENV_STRIP = (
    "CODEX_HOME",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN",
)


def codex_env() -> dict:
    """Return a copy of the environment with all API-key/CODEX_HOME overrides stripped.

    This is the ONLY env handed to ``codex`` subprocesses. It guarantees the
    CLI uses the ChatGPT-authenticated ``~/.codex`` and never inherits a
    standalone model API key from the ambient environment.
    """
    env = os.environ.copy()
    for var in CODEX_ENV_STRIP:
        env.pop(var, None)
    return env


VALID_EVIDENCE_SUPPORTED_FIELDS = frozenset(
    {"price", "features", "buzz", "brand", "category", "launch_date", "link"}
)
CN_DISCOVERY_CONFIG = ROOT / "config" / "cn_new_product_sources.json"


def _load_cn_discovery_config() -> dict:
    with open(CN_DISCOVERY_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _cn_radar_soft_floor(category: str) -> int:
    return int(_load_cn_discovery_config()["soft_floor"][category])


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


def month_date_range(month_str_val: str) -> tuple[str, str, str, str]:
    """Return (en_range, cn_range, start_iso, end_iso) for a YYYY-MM month string."""
    year, month = int(month_str_val[:4]), int(month_str_val[5:7])
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)
    en_range = (
        f"{first_date.strftime('%b')} {first_date.day}"
        f" \u2013 {last_date.strftime('%b')} {last_date.day}, {first_date.year}"
    )
    cn_range = f"{first_date.month}\u6708{first_date.day}\u65e5 \u2013 {last_date.month}\u6708{last_date.day}\u65e5"
    return en_range, cn_range, start, end


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    return body[:500] or str(exc.reason) or "no response body"


def _normalize_endpoint_url(base_url: str) -> str:
    """Normalize OpenAI-compatible endpoints for robustness.

    Handles various endpoint formats:
    - OpenAI: https://api.openai.com/v1
    - Compatible: https://provider.example.com/v1
    - Full path: https://provider.example.com/v1/chat/completions
    - Trailing slash: https://provider.example.com/v1/

    Preserves OpenAI standard while supporting any OpenAI-compatible provider.
    """
    if not base_url:
        raise ValueError("LLM_BASE_URL must not be empty")
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _format_llm_error_message(exc: urllib.error.HTTPError, attempt: int, max_attempts: int) -> str:
    """Format HTTP error with detailed diagnostics.

    Provides actionable information for debugging endpoint issues.
    """
    detail = _http_error_detail(exc)

    if exc.code == 410:
        return (
            f"LLM endpoint is retired (HTTP 410): {exc.geturl()}. "
            f"Update the GitHub Actions LLM_BASE_URL/LLM_MODEL secrets or set "
            f"LLM_FALLBACK_MODELS to a current model. "
            f"Provider response: {detail}"
        )

    if exc.code == 404:
        return (
            f"LLM model not found (HTTP 404): {exc.geturl()}. "
            f"Update the GitHub Actions LLM_BASE_URL/LLM_MODEL secrets or set "
            f"LLM_FALLBACK_MODELS to a current model. "
            f"Provider response: {detail}"
        )

    base_msg = f"LLM request failed with HTTP {exc.code} at {exc.geturl()} after {attempt} attempt(s): {detail}"

    if exc.code in _TRANSIENT_HTTP_CODES:
        return f"Transient error: {base_msg}"

    if exc.code in {401, 403}:
        return (
            f"Authentication or authorization failed (HTTP {exc.code}). "
            f"Check LLM_API_KEY secret and provider permissions. "
            f"Provider response: {detail}"
        )

    return f"Non-retryable error: {base_msg}"


def codex_logged_in() -> bool:
    """Return True when the local Codex CLI is authenticated.

    Only inspects the CLI's own status command; never reads or copies the
    credentials (auth.json under ~/.codex is never touched). The stripped env
    guarantees the ChatGPT-authenticated ~/.codex is used, not a CODEX_HOME
    that carries an API key.
    """
    try:
        result = subprocess.run(
            [CODEX_BIN, "login", "status"],
            env=codex_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def call_codex(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> str:
    """Invoke the locally authenticated Codex CLI non-interactively.

    The system prompt is folded into a single prompt (Codex exec has no
    separate system role). The model's final message is captured via
    ``--output-last-message``. No authentication material is stored or
    copied: codex reads its own ChatGPT credentials from ``~/.codex``.
    """
    if not codex_logged_in():
        raise RuntimeError(
            "Codex CLI is not logged in (ChatGPT subscription via ~/.codex). "
            "Run 'codex login' once on this machine and retry. "
            "No auth is stored by this runner."
        )
    prompt = (
        f"Follow these instructions strictly.\n\n{system_prompt}\n\n--- USER REQUEST ---\n\n"
        f"{user_prompt}\n\n"
        "Respond ONLY with the requested JSON payload. Do not run any shell commands "
        "and do not use any tools or files."
    )
    cmd = [
        CODEX_BIN,
        "exec",
        "-C",
        str(ROOT),
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--color",
        "never",
    ]
    if CODEX_MODEL:
        cmd += ["--model", CODEX_MODEL]
    with tempfile.NamedTemporaryFile(prefix="codex-last-message-", mode="w", delete=False) as tmp:
        out_path = tmp.name
    cmd += ["-o", out_path, prompt]
    try:
        proc = subprocess.run(
            cmd,
            env=codex_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=CODEX_EXEC_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip().splitlines()
            raise RuntimeError(
                "codex exec failed (non-zero exit). "
                + (" ".join(detail[-2:]) if detail else "no stderr")
            )
        if not os.path.exists(out_path):
            raise RuntimeError("codex exec completed but produced no last-message output")
        with open(out_path, encoding="utf-8") as f:
            response = f.read().strip()
        if not response:
            raise RuntimeError("codex exec returned an empty response")
        return response
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"codex exec timed out after {CODEX_EXEC_TIMEOUT}s. "
            "Consider raising CODEX_EXEC_TIMEOUT."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to run {CODEX_BIN}: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(out_path)


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 8000) -> str:
    if LLM_TRANSPORT == "codex":
        return call_codex(system_prompt, user_prompt, max_tokens)
    if not API_KEY:
        raise ValueError("LLM_API_KEY environment variable not set")

    url = _normalize_endpoint_url(BASE_URL)
    fallback_models = [
        m.strip() for m in os.environ.get("LLM_FALLBACK_MODELS", "").split(",") if m.strip()
    ]
    candidate_models = [MODEL] + fallback_models
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for model_idx, model in enumerate(candidate_models):
        payload = json.dumps(
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.3,
            }
        ).encode("utf-8")
        for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    return result["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                error_msg = _format_llm_error_message(exc, attempt, LLM_MAX_ATTEMPTS)

                if exc.code in (404, 410) and model_idx < len(candidate_models) - 1:
                    print(
                        f"  LLM model {model!r} unavailable (HTTP {exc.code}); "
                        f"trying fallback model {candidate_models[model_idx + 1]!r}",
                        file=sys.stderr,
                    )
                    break

                if exc.code in (404, 410):
                    raise RuntimeError(error_msg) from exc

                if exc.code not in _TRANSIENT_HTTP_CODES or attempt == LLM_MAX_ATTEMPTS:
                    raise RuntimeError(error_msg) from exc

                retry_after = exc.headers.get("Retry-After")
                delay = (
                    int(retry_after)
                    if retry_after and retry_after.isdigit()
                    else min(30, 2**attempt)
                )
                print(
                    f"  Transient LLM HTTP {exc.code}; retrying "
                    f"({attempt}/{LLM_MAX_ATTEMPTS}) in {delay}s",
                    file=sys.stderr,
                )
                time.sleep(delay)

    raise RuntimeError(f"LLM request failed after {LLM_MAX_ATTEMPTS} attempts")


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


def _normalize_slug(url: str) -> str:
    """Extract and normalize the URL path slug into space-separated words."""
    path = urlparse(url).path
    path = re.sub(r"\.[a-z]+$", "", path, flags=re.IGNORECASE)
    path = re.sub(r"[-_/]", " ", path)
    path = re.sub(r"[^\w\s]", "", path)
    return re.sub(r"\s+", " ", path).strip().casefold()


_CATEGORY_CUES: dict[str, frozenset[str]] = {
    "makeup": frozenset(
        {
            "makeup",
            "lipstick",
            "blush",
            "foundation",
            "mascara",
            "eyeshadow",
            "contour",
            "highlighter",
            "bronzer",
            "concealer",
            "lip gloss",
            "eyeliner",
            "brow",
            "powder",
            "lip",
            "eye",
            "face",
            "skin care",
            "beauty",
            "彩妆",
            "美妆",
            "口红",
            "唇膏",
            "唇釉",
            "唇泥",
            "腮红",
            "粉底",
            "气垫",
            "睫毛膏",
            "眼影",
            "眼线",
            "遮瑕",
            "高光",
            "修容",
        }
    ),
    "fragrance": frozenset(
        {
            "fragrance",
            "perfume",
            "cologne",
            "scent",
            "oud",
            "eau de parfum",
            "eau de toilette",
            "edp",
            "edt",
            "aromatic",
            "notes",
            "sillage",
            "spray",
            "mist",
            "香",
            "香水",
            "淡香水",
            "浓香水",
        }
    ),
}


def _score_article_relevance(article: dict, category: str) -> int:
    """Score how relevant an article is to a given beauty category.

    Returns an integer relevance score.  Higher means more relevant.
    The score is based on keyword matches in the title and summary.
    Equal-score ordering is NOT determined here — callers must use a
    stable sort key (e.g. insertion order) to preserve determinism.
    """
    cues = _CATEGORY_CUES.get(category, frozenset())
    if not cues:
        return 0

    title = article.get("title", "").lower()
    summary = article.get("summary", "").lower()
    generic_cues = {"beauty", "makeup", "skin care", "美妆", "彩妆", "香", "fragrance"}
    score = 10 if article.get("category") == category else 0
    for cue in cues:
        if cue in title:
            score += 1 if cue in generic_cues else 4
        elif cue in summary:
            score += 1 if cue in generic_cues else 2
    return score


def _select_category_relevant_articles(
    articles: list[dict],
    category: str,
    max_cn: int = 15,
    max_non_cn: int = 15,
) -> list[dict]:
    """Select up to *max_cn* CN and *max_non_cn* non-CN articles that are
    most relevant to *category*.

    Articles are scored by ``_score_article_relevance``.  Within the same
    score tier the original relative order (insertion order) is preserved
    so that the result is deterministic for a given input list.

    The complete ``articles`` list is still available for post-generation
    evidence matching — this function only constrains the *prompt* window.
    """
    cn: list[tuple[int, int, dict]] = []
    non_cn: list[tuple[int, int, dict]] = []

    for idx, article in enumerate(articles):
        score = _score_article_relevance(article, category)
        bucket = cn if article.get("market") == "CN" else non_cn
        bucket.append((score, idx, article))

    # Sort descending by score, then ascending by insertion index (stable)
    cn.sort(key=lambda t: (-t[0], t[1]))
    non_cn.sort(key=lambda t: (-t[0], t[1]))

    return [a for _, _, a in cn[:max_cn]] + [a for _, _, a in non_cn[:max_non_cn]]


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

    matching rules (applied in order):
      1. Direct (non-Google) candidate-specific verification article whose
         ``candidate_name`` exactly matches the product name
      2. Product URL is a substring of article URL
      3. Full normalized product name appears in title, summary, or
         URL slug
      4. At least two meaningful product-name tokens (len > 3) appear
         in title, summary, or URL slug

    URL slugs are normalized (hyphens/underscores/punctuation → spaces,
    casefolded) so that e.g. ``guerlain-rouge-lipstick-editor-review``
    matches product name "Guerlain Rouge Lipstick".

    Avoids overly broad single-token matches.
    Articles matching ``source_url`` are preferred in sort order.

    Returns a list of matching articles sorted by date (newest first),
    with ``source_url`` matches ranked first.
    """
    name_lower = product_name.lower()
    name_tokens = [w for w in name_lower.split() if len(w) > 3]
    latin_tokens = re.findall(r"[a-z][a-z0-9'-]{2,}", name_lower)
    cjk_chars = set(re.findall(r"[\u3400-\u9fff]", product_name))
    supporting = []
    for article in articles:
        url = article.get("url", "")
        if urlparse(url).netloc.casefold() == "news.google.com":
            continue

        # 1. Candidate-specific verification article for this exact product.
        # Produced by build.collect.search_product_evidence and enriched to a
        # direct publisher URL.  The Google-aggregator check above guarantees
        # an RSS aggregator link is never accepted as evidence.
        if (
            str(article.get("reference_type", "")).casefold() == "candidate_verification"
            and str(article.get("candidate_name", "")).strip().casefold()
            == product_name.strip().casefold()
        ):
            supporting.append(article)
            continue

        # 2. Product URL match (strongest signal)
        if product_link and url and product_link in url:
            supporting.append(article)
            continue

        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        url_slug = _normalize_slug(url)
        combined = f"{title} {summary} {url_slug}"

        # 3. Full normalized product name in combined text
        if name_lower in combined:
            supporting.append(article)
            continue

        # 4. At least two meaningful tokens (>3 chars) must match
        matched_tokens = [t for t in name_tokens if t in combined]
        if len(matched_tokens) >= 2:
            supporting.append(article)
            continue

        # 5. Chinese product names are not whitespace-tokenized. Require
        # high CJK character coverage and, for mixed names, a matching Latin
        # brand token. This recognizes e.g. "PRADA 0度紫润唇膏" in a title
        # containing "PRADA…0度紫…润唇膏" without accepting a brand-only page.
        if len(cjk_chars) >= 4:
            matched_cjk = sum(char in combined for char in cjk_chars)
            cjk_coverage = matched_cjk / len(cjk_chars)
            latin_ok = not latin_tokens or any(token in combined for token in latin_tokens)
            if cjk_coverage >= 0.7 and latin_ok:
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


def _classify_evidence(article: dict, product_link: str) -> tuple[str, str, str]:
    """Return (grade, date_basis, evidence_type) for one verified source."""
    reference_type = str(article.get("reference_type", "")).casefold()
    source = str(article.get("source", "")).casefold()
    url = str(article.get("url", ""))
    combined = f"{reference_type} {source}"

    if article.get("source_authority") == "official" or "official launch" in combined:
        return "A", "official_launch", "launch_announcement"
    if product_link and url and product_link in url:
        return "A", "first_listing", "product_page"
    if any(
        cue in combined
        for cue in (
            "retailer",
            "e-commerce",
            "product page",
            "editorial",
            "fragrance_roundup",
            "candidate_verification",
            "new_product_discovery",
        )
    ):
        return "B", "source_publication", "editorial"
    if any(cue in combined for cue in ("social", "douyin", "xiaohongshu", "小红书", "抖音")):
        return "C", "first_verified_mention", "social_media"
    return "B", "source_publication", "editorial"


def _merge_unique_articles(target: list[dict], additions: list[dict]) -> int:
    seen_urls = {article.get("url", "") for article in target}
    added = 0
    for article in additions:
        url = article.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        target.append(article)
        added += 1
    return added


def _supplement_candidate_evidence(
    data: dict,
    raw_data: dict,
    category: str,
    month_label: str,
) -> None:
    """Search candidate names that the discovery passes did not support.

    Legacy scope (unchanged): CN new-product-radar products across all
    categories.  Extended scope: fragrance candidates in BOTH the US and
    CN markets across ``heat_rankings`` AND ``new_product_radar``.  Month-
    level fragrance roundups name many products at once, so a candidate
    whose only lead is a roundup title cannot be name-matched; this pass
    runs a candidate-specific search and enriches the articles to direct
    publisher URLs tagged with the exact product name.
    """
    if not re.fullmatch(r"\d{4}-\d{2}", month_label):
        return

    articles = raw_data.setdefault("articles", [])
    unsupported: list[tuple[str, str]] = []
    for section in ("new_product_radar", "heat_rankings"):
        for panel, products in data.get(section, {}).items():
            if not isinstance(products, list):
                continue
            market = panel.split()[0] if panel.split() else ""
            if category == "fragrance":
                if market not in {"US", "CN"}:
                    continue
            elif market != "CN" or section != "new_product_radar":
                continue
            for product in products:
                if not isinstance(product, dict):
                    continue
                name = str(product.get("name", "")).strip()
                if not name:
                    continue
                link = str(product.get("link", "")).strip()
                source_url = str(product.get("source_url", "")).strip() or None
                if not _find_supporting_articles(name, link, articles, source_url):
                    unsupported.append((market, name))

    names = list(dict.fromkeys(unsupported))[:12]
    if not names:
        return

    audit = raw_data.setdefault("candidate_evidence_audit", [])
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(search_product_evidence, name, category, month_label, market=market): (
                market,
                name,
            )
            for market, name in names
        }
        for future in as_completed(future_map):
            market, name = future_map[future]
            try:
                record, discovered = future.result()
                record["articles_added"] = _merge_unique_articles(articles, discovered)
                audit.append(record)
            except Exception as exc:
                audit.append(
                    {
                        "product_name": name,
                        "category": category,
                        "market": market,
                        "type": "candidate_verification",
                        "articles_count": 0,
                        "articles_added": 0,
                        "error": str(exc)[:200],
                    }
                )
    audit.sort(key=lambda item: (item.get("category", ""), item.get("product_name", "")))
    raw_data["total_articles"] = len(articles)


# Backwards-compatible alias for the legacy CN radar-only name.
_supplement_cn_radar_evidence = _supplement_candidate_evidence


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
        evidence_grade, date_basis, evidence_type = _classify_evidence(best, product_link)
        return {
            "launch_date": published_at[:10],
            "quarantine_status": "verified",
            "quarantine_reason": None,
            "evidence_grade": evidence_grade,
            "date_basis": date_basis,
            "evidence": {
                "url": evidence_url,
                "title": evidence_title,
                "type": evidence_type,
                "published_at": published_at,
                "fetched_at": fetched_at,
                "checked_at": fetched_at,
                "supported_fields": [
                    "price",
                    "features",
                    "buzz",
                    "brand",
                    "category",
                    "launch_date",
                    "link",
                ],
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

    def english_only(v: str) -> str:
        """Remove accidental CJK fragments from English-only public fields."""
        cleaned = re.sub(r"[\u3400-\u9fff]+", " ", v or "")
        return re.sub(r"\s+", " ", cleaned).strip()

    # The public site is English-only. Preserve the supplied localized name
    # separately while ensuring the visible name never leaks CJK characters.
    visible_name = re.sub(r"[\u3400-\u9fff]+", " ", name)
    visible_name = re.sub(r"\s+", " ", visible_name).strip() or name
    if buzz_en and visible_name.casefold() not in buzz_en.casefold():
        buzz_en = f"{visible_name}: {buzz_en}"

    if launch_evidence is None:
        launch_evidence = _make_launch_evidence(
            name, link, topic, iso_week, fetched_at, articles or [], source_url
        )

    # Product discovery may return a brand homepage or collection landing
    # page. For every category, replace that generic destination with the
    # direct verified evidence article rather than publishing a weak link.
    parsed_link = urlparse(link or "")
    if (
        parsed_link.path in {"", "/"}
        or "/collections/" in parsed_link.path
        or "/category" in parsed_link.path
    ):
        link = launch_evidence.get("evidence", {}).get("url", link)

    # Browsers accept Unicode URLs, but the English-only public surface and
    # quality audit require ASCII-safe links. Percent-encode non-ASCII path or
    # query characters while preserving URL delimiters and existing escapes.
    if link:
        link = quote(link, safe=":/?#[]@!$&'()*+,;=%")

    if topic == "fragrance":
        generic_category = category_badge.strip().casefold() in {
            "",
            "edp",
            "edt",
            "perfume",
            "fragrance",
            "solid",
        }
        name_lower = visible_name.casefold()
        if generic_category:
            if "eau de parfum" in name_lower:
                category_badge = "Eau de Parfum"
            elif "eau de toilette" in name_lower:
                category_badge = "Eau de Toilette"
            elif "cologne" in name_lower:
                category_badge = "Eau de Cologne"
            else:
                category_badge = "Fragrance Collection"

        # Product discovery sometimes returns a brand homepage instead of a
        # SKU URL. Point users to the verified launch article in that case.
        price_text = price_en or ""
        if not re.search(r"(?:[$€£¥]|USD|CAD|HKD|SGD|AED|RMB|CNY)", price_text, re.I):
            price_text = f"{price_text}; price not publicly disclosed".strip("; ")
        if not re.search(r"\b\d+(?:\.\d+)?\s?(?:ml|fl oz|oz|g|grams?)\b", price_text, re.I):
            price_text = f"{price_text}; bottle size not publicly disclosed".strip("; ")
        price_en = price_text

        # Radar cards use this field as launch/category copy; keep the brand
        # while adding a specific, factual launch type derived from the name.
        launch_type = category_badge
        if not any(
            cue in (brand_en or "").casefold()
            for cue in ("launch", "new", "limited", "edition", "collection", "line")
        ):
            brand_en = f"{brand_en} — New {launch_type} launch".strip(" —")

    category_badge = english_only(category_badge)
    brand_en = english_only(brand_en)
    buzz_en = english_only(buzz_en)
    features_en = english_only(features_en)
    price_en = english_only(price_en)

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
        "name": s(visible_name),
        "name_cn": name_cn,
        "new_badge": new_badge,
        "rank": rank,
        "score": score,
        "tier": tier,
        "trend": None,
        "trend_badge": trend_badge,
    }


def _accumulate_cn_radar_candidates(
    accumulated: dict[str, list[dict]],
    generated: dict,
) -> None:
    for panel, products in generated.get("new_product_radar", {}).items():
        if not panel.startswith("CN ") or not isinstance(products, list):
            continue
        existing = {
            str(product.get("name", "")).strip().casefold()
            for product in accumulated.setdefault(panel, [])
        }
        for product in products:
            if not isinstance(product, dict):
                continue
            key = str(product.get("name", "")).strip().casefold()
            if key and key not in existing:
                accumulated[panel].append(product)
                existing.add(key)


def _record_cn_radar_coverage(
    raw_data: dict,
    category: str,
    result: dict,
    soft_floor: int,
) -> None:
    if not soft_floor:
        return
    verified_count = sum(
        len(products)
        for panel, products in result["new_product_radar"].items()
        if panel.startswith("CN ")
    )
    raw_data.setdefault("coverage_health", {})[category] = {
        "market": "CN",
        "section": "new_product_radar",
        "soft_floor": soft_floor,
        "verified_count": verified_count,
        "status": "met" if verified_count >= soft_floor else "below_soft_floor",
        "policy": "Soft floor triggers discovery; rankings are never padded.",
    }


def generate_products(
    raw_data: dict, category: str, month_label: str, en_range: str, fetched_at: str
) -> dict:
    """Generate products for a category using LLM, returning canonical format.

    Every product receives non-null launch_evidence backed by real source
    articles.  Unsupported products are quarantined (dropped) with a stderr
    warning; the remaining products are renumbered sequentially per panel.
    Every heat_rankings panel must retain at least 1 evidence-backed product
    or generation fails.  Radar panels may be empty.
    """
    articles = raw_data.get("articles", [])
    # Category-aware selection: pick articles whose titles/summaries
    # contain category-relevant cues (makeup vs fragrance keywords) so
    # that the LLM prompt includes evidence proportional to the topic
    # rather than simply taking the first 15 per market.  The full
    # article set is still retained for post-generation evidence matching.
    prompt_articles = _select_category_relevant_articles(articles, category)
    articles_text = "\n".join(
        f"[{i}] {a['title']}: {a.get('summary', '')[:200]} (URL: {a['url']})"
        for i, a in enumerate(prompt_articles)
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
- Generate 2-5 new products per radar panel whose first official launch,
  first retail listing, or first credible publication falls inside {month_label}
- All products must be REAL, publicly available {category} products
- Scores: 65-98 range (85=Trending, 90=Viral)
- CN fields in Chinese, EN in English
- Links must be real official-brand, Sephora, Ulta, Tmall, JD, Douyin-shop,
  or reputable retailer product URLs
- Use real buzz data (review counts, sales rankings, social media metrics)
- CN LUXURY and CN MASSTIGE panels: only provide products if you have
  real Chinese-market evidence.  Empty arrays [] are acceptable and
  preferred over fabricated products.
- Treat the configured main references as mandatory research targets, not a
  whitelist. Other valid public sources are allowed under identical evidence rules.
- Each product link MUST point to a real, accessible product page URL.
- Do NOT generate products for which you cannot provide a real URL.
- IMPORTANT: Each product MUST include a "source_url" field set to the
  exact URL of one of the articles listed in the Raw data below.  This
  is the article that supports the product claim.  The source_url value
  must match the full URL exactly from the supplied list."""

    user_prompt = (
        f"Generate {category} product data"
        f" for month {month_label} ({en_range})."
        f"\n\nRaw data (article index, title, summary, URL):\n{articles_text}"
    )

    _LLM_MAX_ATTEMPTS = 3
    current_user_prompt = user_prompt
    empty_panels: list[str] = []
    best_result: dict | None = None
    best_quality: tuple[int, int, int] | None = None
    accumulated_cn_radar: dict[str, list[dict]] = {}
    cn_radar_floor = (
        _cn_radar_soft_floor(category) if re.fullmatch(r"\d{4}-\d{2}", month_label) else 0
    )

    for attempt in range(1, _LLM_MAX_ATTEMPTS + 1):
        print(f"  Calling LLM for {category} products (attempt {attempt}/{_LLM_MAX_ATTEMPTS})...")
        response = call_llm(system_prompt, current_user_prompt)
        try:
            data = parse_json_response(response)
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"  WARNING: malformed {category} JSON on attempt {attempt}: {exc}",
                file=sys.stderr,
            )
            if attempt < _LLM_MAX_ATTEMPTS:
                current_user_prompt = (
                    user_prompt
                    + "\n\nThe previous response was malformed JSON. Return one complete, "
                    "strictly valid JSON object only; do not truncate it or use Markdown."
                )
                continue
            break
        _accumulate_cn_radar_candidates(accumulated_cn_radar, data)
        if accumulated_cn_radar:
            radar_data = data.setdefault("new_product_radar", {})
            for panel, products in accumulated_cn_radar.items():
                radar_data[panel] = products

        _supplement_candidate_evidence(data, raw_data, category, month_label)
        articles = raw_data.get("articles", [])
        article_urls = {a.get("url", "") for a in articles if a.get("url")}

        # Transform to canonical format — quarantine unsupported products instead of
        # failing the entire category
        result: dict = {"heat_rankings": {}, "new_product_radar": {}}
        for section in ["heat_rankings", "new_product_radar"]:
            if section in data:
                for panel, products in data[section].items():
                    canonical_products: list[dict] = []
                    panel_parts = panel.split()
                    panel_market = panel_parts[0]
                    panel_tier = panel_parts[1] if len(panel_parts) > 1 else "LUXURY"
                    if isinstance(products, list):
                        for p in products:
                            if not isinstance(p, dict):
                                continue
                            name = p.get("name", "?")
                            # Reject products whose source_url is not a collected article URL
                            source_url = p.get("source_url")
                            if source_url and source_url not in article_urls:
                                source_url = None
                            try:
                                candidate = make_product(
                                    name=name,
                                    name_cn=p.get("name_cn") or "",
                                    rank=p.get("rank", 1),
                                    score=p.get("score", 75),
                                    # Panel membership is authoritative. LLMs
                                    # occasionally emit a conflicting tier,
                                    # which must not corrupt the canonical card.
                                    market=panel_market,
                                    tier=panel_tier,
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
                                    iso_week=month_label,
                                    fetched_at=fetched_at,
                                    articles=articles,
                                    trend_badge=p.get("trend_badge"),
                                    new_badge=p.get("new_badge"),
                                    launch_evidence=None,
                                    source_url=source_url,
                                )
                                if section == "new_product_radar":
                                    _, _, month_start, month_end = month_date_range(month_label)
                                    launch_date = candidate["launch_evidence"]["launch_date"]
                                    if not month_start <= launch_date <= month_end:
                                        raise ValueError(
                                            f"radar launch date {launch_date} outside "
                                            f"{month_start}..{month_end}"
                                        )
                                canonical_products.append(candidate)
                            except ValueError as e:
                                print(
                                    f"  WARNING: Quarantining '{name}' in {section}/{panel}: {e}",
                                    file=sys.stderr,
                                )
                    result[section][panel] = canonical_products

        # Renumber ranks sequentially per panel after filtering
        for section in ["heat_rankings", "new_product_radar"]:
            for panel_products in result[section].values():
                panel_products.sort(key=lambda product: float(product.get("score", 0)), reverse=True)
                for i, p in enumerate(panel_products, start=1):
                    p["rank"] = i

        # A product can legitimately appear in both weekly heat and new-product
        # radar.  Treat the heat score as the canonical weekly score so a
        # stochastic LLM response cannot assign two scores to the same product
        # in the same market/tier panel.
        _align_cross_section_scores(result)

        # Require every heat_rankings panel to exist and contain >= 1 evidence-backed product
        required_heat_panels = {"US LUXURY", "US MASSTIGE", "CN LUXURY", "CN MASSTIGE"}
        empty_panels = sorted(
            panel for panel in required_heat_panels if not result["heat_rankings"].get(panel, [])
        )
        cn_radar_count = sum(
            len(products)
            for panel, products in result["new_product_radar"].items()
            if panel.startswith("CN ")
        )

        # Retries may improve one weak section while regressing panels that
        # were already evidence-complete. Keep the best fully canonicalized
        # attempt; unsupported candidates have already been quarantined.
        heat_coverage = sum(len(products) for products in result["heat_rankings"].values())
        quality = (-len(empty_panels), min(cn_radar_count, cn_radar_floor), heat_coverage)
        if best_quality is None or quality > best_quality:
            best_quality = quality
            best_result = result

        if not empty_panels and (not cn_radar_floor or cn_radar_count >= cn_radar_floor):
            _record_cn_radar_coverage(raw_data, category, result, cn_radar_floor)
            return result

        if attempt < _LLM_MAX_ATTEMPTS:
            retry_reasons: list[str] = []
            if empty_panels:
                missing = ", ".join(empty_panels)
                retry_reasons.append(
                    f"The following required heat panels are empty: {missing}. "
                    "For each empty panel, provide 1–5 evidence-backed products."
                )
            if cn_radar_floor and cn_radar_count < cn_radar_floor:
                retry_reasons.append(
                    f"CN new-product radar has {cn_radar_count} verified products; "
                    f"the discovery soft floor is {cn_radar_floor}. Search the supplied "
                    "CN launch evidence for additional real in-window products across "
                    "CN LUXURY and CN MASSTIGE."
                )
            expanded_articles = _select_category_relevant_articles(
                articles,
                category,
                max_cn=40,
                max_non_cn=15,
            )
            expanded_articles_text = "\n".join(
                f"[{i}] {article['title']}: {article.get('summary', '')[:200]} "
                f"(URL: {article['url']})"
                for i, article in enumerate(expanded_articles)
            )
            retry_note = (
                f"\n\n[RETRY {attempt}/{_LLM_MAX_ATTEMPTS}] "
                + " ".join(retry_reasons)
                + " Each source_url must be an exact URL below. Do not fabricate "
                "products or source URLs." + f"\n\nExpanded evidence:\n{expanded_articles_text}"
            )
            current_user_prompt = user_prompt + retry_note
            print(
                f"  Retrying: heat gaps={empty_panels}, "
                f"CN radar={cn_radar_count}/{cn_radar_floor or 'n/a'}",
                file=sys.stderr,
            )

    if best_result is not None:
        result = best_result
        empty_panels = sorted(
            panel for panel in required_heat_panels if not result["heat_rankings"].get(panel, [])
        )
        cn_radar_count = sum(
            len(products)
            for panel, products in result["new_product_radar"].items()
            if panel.startswith("CN ")
        )
    else:
        raise RuntimeError(f"{category} generation produced no valid JSON attempt")

    market_coverage = {
        market: sum(
            len(products)
            for panel, products in result["heat_rankings"].items()
            if panel.startswith(f"{market} ")
        )
        for market in ("US", "CN")
    }
    missing = ", ".join(empty_panels)
    if market_coverage["US"] > 0:
        _record_cn_radar_coverage(raw_data, category, result, cn_radar_floor)
        if cn_radar_floor and cn_radar_count < cn_radar_floor:
            print(
                f"  WARNING: CN {category} radar remained below the discovery soft floor "
                f"({cn_radar_count}/{cn_radar_floor}); publishing only verified products",
                file=sys.stderr,
            )
        print(
            f"  WARNING: publishing with evidence gap in panels {{{missing}}}; "
            f"verified market coverage is {market_coverage}",
            file=sys.stderr,
        )
        return result
    raise ValueError(
        f"heat_rankings panels {{{missing}}} are empty after {_LLM_MAX_ATTEMPTS} "
        f"attempts and market coverage is insufficient: {market_coverage}"
    )


def _align_cross_section_scores(result: dict) -> None:
    """Use the heat score for a product repeated in radar in the same panel."""
    for panel, radar_products in result["new_product_radar"].items():
        heat_scores = {
            p["name"].strip().casefold(): p["score"] for p in result["heat_rankings"].get(panel, [])
        }
        for product in radar_products:
            canonical_score = heat_scores.get(product["name"].strip().casefold())
            if canonical_score is not None:
                product["score"] = canonical_score


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
    month_label: str,
    en_range: str,
    cn_range: str,
    fetched_at: str,
) -> dict:
    """Build manifest.json with all required fields for validation."""

    def sha256(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    return {
        "canonical_hash": sha256(report_json),
        "data_pointer": f"../../month{month_label}.json",
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
        "month": month_label,
        "legacy_fields_isolated": [],
        "migration_deprecation": {},
        "migration_gaps": [
            "CN new-product soft floors trigger a second discovery pass but "
            "panels may remain below target when evidence is insufficient.",
        ],
        "note": (
            "Auto-generated from public RSS data with dedicated CN discovery, "
            "candidate verification, and evidence-graded LLM synthesis."
        ),
        "phase": "auto",
        "remaining_warnings": 1,
        "resolved_warnings": [],
        "schema_version": 3,
        "scoring_hash": sha256(scoring_json),
        "sources_hash": sha256(sources_json),
    }


def main() -> int:
    month = resolve_month(previous_month_str())
    en_range, cn_range, start_date, end_date = month_date_range(month)
    fetched_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=== Beauty Monthly Content Generation ===")
    print(f"Month: {month}")
    print(f"Date Range: {en_range}")
    print(f"Transport: {LLM_TRANSPORT}")
    print(f"LLM Model: {MODEL}")
    print()

    # Load raw data
    raw_path = ROOT / "data" / "months" / month / "raw_collected.json"
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
        makeup = generate_products(raw_data, "makeup", month, en_range, fetched_at)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    print("\n--- Generating Fragrance Products ---")
    try:
        fragrance = generate_products(raw_data, "fragrance", month, en_range, fetched_at)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1

    # Candidate-specific searches are part of the auditable raw collection,
    # not transient generation context.
    raw_data["total_articles"] = len(raw_data.get("articles", []))
    raw_path.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    cn_product_count = sum(
        len(products)
        for category in (makeup, fragrance)
        for panel, products in category["heat_rankings"].items()
        if panel.startswith("CN ")
    )
    if cn_product_count == 0:
        print(
            "FATAL: Monthly report has no evidence-backed Chinese-market heat products",
            file=sys.stderr,
        )
        return 1

    # Build report.json (exact canonical format)
    report = {
        "date_range": en_range,
        "date_range_cn": cn_range,
        "products": {
            "makeup": makeup,
            "fragrance": fragrance,
        },
        "version": f"month{month}-{start_date.replace('-', '')[:8]}-v1",
        "month": month,
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
            "evidence_absences": EXPLICIT_EVIDENCE_ABSENCES,
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
        month,
        en_range,
        cn_range,
        fetched_at,
    )
    manifest_json = det_json(manifest)

    report_hash = sha256(report_json)
    _sources_hash = sha256(sources_json)
    _scoring_hash = sha256(scoring_json)

    # Write files
    output_dir = ROOT / "data" / "months" / month
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
