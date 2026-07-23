"""Historical monthly trend inference helpers.

These rules are intentionally narrow and evidence-driven.  They are only
used for the recovered June 2026 monthly report, where some preserved radar
rows carry product-specific detail text but no explicit canonical trend tag.
"""

from __future__ import annotations

from collections.abc import Iterable

EXPLICIT_PRODUCT_TAGS: dict[tuple[str, str], str] = {
    ("makeup", "heart on lipstick"): "Functional Lip",
    ("makeup", "marc jacobs heart on lipstick"): "Functional Lip",
    ("makeup", "viva glam"): "Functional Lip",
    ("makeup", "mac x chappell roan viva glam"): "Functional Lip",
    ("makeup", "shade & illuminate foundation"): "Skincare Foundation",
    ("makeup", "tom ford shade & illuminate foundation"): "Skincare Foundation",
    ("makeup", "毛戈平 光韵奢华粉底霜"): "Skincare Foundation",
    ("makeup", "酵色 贝壳系列唇泥（新色）"): "Low-Saturation Pastel",
    ("makeup", "tower 28 splashy cream blush hydrating gel"): "Low-Saturation Pastel",
    ("makeup", "splashy cream blush hydrating gel"): "Low-Saturation Pastel",
    ("makeup", "money shot highlighter gel"): "Low-Saturation Pastel",
    ("makeup", "marc jacobs money shot highlighter gel"): "Low-Saturation Pastel",
    ("fragrance", "thé impérial"): "Matcha Fragrance",
    ("fragrance", "l'amant"): "Oriental Narrative",
    ("fragrance", "rosa rossa"): "Rose Revival",
    ("fragrance", "rose whip"): "Rose Revival",
    ("fragrance", "cheirosa 91"): "Rose Revival",
    ("fragrance", "you solid"): "Milky Musk",
    ("fragrance", "11 11 moon"): "Milky Musk",
    ("fragrance", "mochi milk"): "Milky Musk",
}

TEXT_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "makeup": {
        "Skincare Foundation": (
            "skincare foundation",
            "premium-base",
            "glow foundation",
            "tinted moisturizer",
            "底妆",
            "养肤",
            "光泽肌",
        ),
        "Functional Lip": (
            "lip treatment",
            "lip balm",
            "lipstick",
            "viva glam",
            "唇膏",
            "唇霜",
        ),
        "Low-Saturation Pastel": (
            "low-saturation",
            "pastel",
            "shell sheen",
            "贝壳光泽",
            "低饱和",
            "lavender duo-chrome",
            "hydrating gel blush",
        ),
    },
    "fragrance": {
        "Matcha Fragrance": (
            "matcha",
            "tea-forward",
            "imperial tea",
            "tea franchise",
        ),
        "Rose Revival": (
            "rose renaissance",
            "heritage rose",
            "3-rose combo",
            "body mist format",
            "mass-market rose entry",
        ),
        "Milky Musk": (
            "skin scent",
            "white musk",
            "milky",
            "mochi",
            "soft musk",
        ),
        "Oriental Narrative": (
            "oriental narrative",
            "oriental-inspired",
            "oud",
            "culturally rooted oriental",
        ),
    },
}


def infer_monthly_historical_trend(
    topic: str,
    product_name: str,
    texts: Iterable[str],
) -> str | None:
    """Infer a canonical trend tag from preserved monthly historical text."""

    normalized_name = (product_name or "").strip().casefold()
    direct = EXPLICIT_PRODUCT_TAGS.get((topic, normalized_name))
    if direct:
        return direct

    haystack = " ".join(
        ((product_name or "").strip(), *((text or "").strip() for text in texts if text))
    ).casefold()
    for tag, patterns in TEXT_PATTERNS.get(topic, {}).items():
        for pattern in patterns:
            if pattern.casefold() in haystack:
                return tag
    return None
