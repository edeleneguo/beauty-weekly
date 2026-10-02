"""Deterministic evidence pools for monthly product discovery."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

CATEGORY_CUES = {
    "makeup": (
        "makeup",
        "lipstick",
        "lip gloss",
        "mascara",
        "blush",
        "foundation",
        "concealer",
        "eyeshadow",
        "eyeliner",
        "bronzer",
        "highlighter",
        "彩妆",
        "口红",
        "唇",
        "腮红",
        "粉底",
        "眼影",
        "睫毛膏",
    ),
    "fragrance": (
        "fragrance",
        "perfume",
        "cologne",
        "scent",
        "eau de parfum",
        "eau de toilette",
        "edp",
        "edt",
        "oud",
        "香水",
        "香氛",
        "淡香水",
        "浓香水",
    ),
}
LUXURY_CUES = (
    "luxury",
    "prestige",
    "premium",
    "dior",
    "chanel",
    "gucci",
    "armani",
    "ysl",
    "tom ford",
    "奢华",
    "高端",
)
MASSTIGE_CUES = (
    "masstige",
    "mass market",
    "drugstore",
    "affordable",
    "e.l.f.",
    "nyx",
    "maybelline",
    "l'oréal paris",
    "平价",
    "大众",
)


@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    title: str
    excerpt: str
    url: str
    market: str
    tiers: tuple[str, ...]
    date: str
    authority: str
    relevance: int
    order: int

    def prompt_line(self) -> str:
        return (
            f"[{self.candidate_id}] {self.title}: {self.excerpt} "
            f"(URL: {self.url})"
        )


def _normalized_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _contains(text: str, cue: str) -> bool:
    if re.search(r"[\u3400-\u9fff]", cue):
        return cue in text
    return bool(re.search(r"\b" + re.escape(cue) + r"\b", text))


def _relevance(article: dict, category: str) -> int:
    title = str(article.get("title", "")).casefold()
    body = f"{title} {article.get('summary', '')} {article.get('url', '')}".casefold()
    opposite = "fragrance" if category == "makeup" else "makeup"
    title_target = sum(_contains(title, cue) for cue in CATEGORY_CUES[category])
    title_opposite = sum(_contains(title, cue) for cue in CATEGORY_CUES[opposite])
    if title_opposite and not title_target:
        return 0
    return title_target * 4 + sum(_contains(body, cue) for cue in CATEGORY_CUES[category])


def _tiers(article: dict) -> tuple[str, ...]:
    text = f"{article.get('title', '')} {article.get('summary', '')}".casefold()
    luxury = any(cue in text for cue in LUXURY_CUES)
    masstige = any(cue in text for cue in MASSTIGE_CUES)
    if luxury and not masstige:
        return ("LUXURY",)
    if masstige and not luxury:
        return ("MASSTIGE",)
    return ("LUXURY", "MASSTIGE")


def build_evidence_pool(
    articles: list[dict], category: str, month: str
) -> list[EvidenceCandidate]:
    del month  # The collector already bounds the corpus to the reporting month.
    if category not in CATEGORY_CUES:
        raise ValueError(f"unsupported category: {category}")
    by_url: dict[str, EvidenceCandidate] = {}
    for order, article in enumerate(articles):
        url = _normalized_url(str(article.get("url", "")))
        relevance = _relevance(article, category)
        if not url or relevance <= 0 or urlsplit(url).netloc.casefold() == "news.google.com":
            continue
        authority = str(article.get("source_authority", "editorial") or "editorial")
        candidate = EvidenceCandidate(
            candidate_id="src_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12],
            title=str(article.get("title", "")).strip(),
            excerpt=str(article.get("summary", "")).strip()[:500],
            url=url,
            market="CN" if article.get("market") == "CN" else "US",
            tiers=_tiers(article),
            date=str(article.get("date", "")),
            authority=authority,
            relevance=relevance,
            order=order,
        )
        existing = by_url.get(url)
        if existing is None or candidate.relevance > existing.relevance:
            by_url[url] = candidate
    authority_rank = {"official": 0, "retailer": 1, "editorial": 2}
    return sorted(
        by_url.values(),
        key=lambda candidate: (
            authority_rank.get(candidate.authority.casefold(), 3),
            -candidate.relevance,
            candidate.order,
        ),
    )


def panel_candidates(
    pool: list[EvidenceCandidate], panel: str, *, limit: int | None = None
) -> list[EvidenceCandidate]:
    market, tier = panel.split(maxsplit=1)
    selected = [
        candidate
        for candidate in pool
        if candidate.market == market and tier in candidate.tiers
    ]
    selected.sort(key=lambda candidate: (len(candidate.tiers), candidate.order))
    return selected[:limit] if limit is not None else selected
