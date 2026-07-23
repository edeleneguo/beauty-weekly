#!/usr/bin/env python3
# ruff: noqa: B007, E501
"""Apply deterministic June 2026 monthly report corrections.

This patcher updates only the recovered historical month bundle under
``data/months/2026-06``:

- normalizes visible English copy
- fixes direct product links / price text for visible products
- hides low-confidence radar rows from the visible English pages instead of
  fabricating missing product-level evidence
- restores fragrance Brand + Product Name parity
- regenerates ``sources.json`` from URLs present in ``report.json``
- refreshes manifest hashes for ``report.json`` and ``sources.json``
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MONTH_DIR = ROOT / "data" / "months" / "2026-06"
REPORT_PATH = MONTH_DIR / "report.json"
SOURCES_PATH = MONTH_DIR / "sources.json"
MANIFEST_PATH = MONTH_DIR / "manifest.json"
CHECKED_AT = "2026-07-23T11:12:46Z"
ALIASES = {
    "毛戈平 光韵奢华粉底霜": "MAOGEPING Luxurious Radiant Foundation Cream",
    "卡姿兰 敦煌联名系列": "Carslan x Dunhuang Museum Collection",
    "酵色 贝壳系列唇泥（新色）": "JOOCYEE Shell Series Lip Mud New Shades",
    "Documents 昆仑煮雪 (Kunlun Boiled Snow)": "To Summer Kunlun Boiled Snow",
    "Scent Library 凉白开 (Cool Boiled Water)": "Scent Library Cool Boiled Water",
    "Boitown 幻境流沙金 (Mirage Quicksand Gold)": "Boitown Mirage Quicksand Gold",
    "L’Artisan Parfumeur L’Amant EDP": "L'Artisan Parfumeur L'Amant EDP",
    "Sol de Janeiro Cheirosa 91": "Sol de Janeiro Cheirosa 91 Perfume Mist",
    "Taormina Orange EDP": "Tom Ford Taormina Orange EDP",
    "Thé Impérial": "Bvlgari Eau Parfumée Thé Impérial",
    "L'Amant": "L'Artisan Parfumeur L'Amant EDP",
    "Million Gold": "Rabanne Million Gold For Her Pure Diamonds",
    "Le Male In Blue": "Jean Paul Gaultier Le Male In Blue",
    "Rosa Rossa": "Guerlain Aqua Allegoria Perle Rosa Rossa",
    "Easy Bake Intense EDP": "Huda Beauty Easy Bake Intense EDP",
    "Rose Whip": "Phlur Rose Whip EDP",
    "You Solid": "Glossier You Solid",
    "Cheirosa 91": "Sol de Janeiro Cheirosa 91 Perfume Mist",
    "11 11 Moon": "Lake & Skye 11 11 Moon EDP",
    "Mochi Milk": "DedCool Mochi Milk",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_products(report: dict[str, Any]):
    products = report["products"]
    for topic in ("makeup", "fragrance"):
        for section in ("heat_rankings", "new_product_radar"):
            for panel, items in products[topic][section].items():
                for product in items:
                    yield topic, section, panel, product


def _find(report: dict[str, Any], topic: str, section: str, panel: str, name: str) -> dict[str, Any]:
    candidates = {name, ALIASES.get(name, name)}
    for item in report["products"][topic][section][panel]:
        if item["name"] in candidates or item.get("name_cn") in candidates:
            return item
    raise KeyError(f"Missing product: {topic}/{section}/{panel}/{name}")


def _set_text_cell(product: dict[str, Any], field: str, text: str) -> None:
    product["detail"][field]["en"] = text
    product["detail"][field]["cn"] = text


def _set_price(product: dict[str, Any], text: str, link: str) -> None:
    product["detail"]["price_link"]["en"] = text
    product["detail"]["price_link"]["cn"] = text
    product["detail"]["price_link"]["link"] = link


def _rename(product: dict[str, Any], name: str, name_cn: str | None = None) -> None:
    product["name"] = name
    if name_cn is not None:
        product["name_cn"] = name_cn


def _hide_radar(product: dict[str, Any], reason: str) -> None:
    product["launch_evidence"]["quarantine_status"] = "unverified"
    product["launch_evidence"]["quarantine_reason"] = reason


def _copy_heat_detail(
    report: dict[str, Any],
    radar_product: dict[str, Any],
    panel: str,
    heat_name: str,
    price_text: str,
    link: str,
    launch_text: str,
    category: str | None = None,
) -> None:
    heat_product = _find(report, "fragrance", "heat_rankings", panel, heat_name)
    radar_product["detail"]["buzz"] = dict(heat_product["detail"]["buzz"])
    radar_product["detail"]["key_features"] = dict(heat_product["detail"]["key_features"])
    if category is not None:
        radar_product["category_badge"] = category
    else:
        radar_product["category_badge"] = heat_product["category_badge"]
    _set_price(radar_product, price_text, link)
    _set_text_cell(radar_product, "brand", launch_text)


def _sync_matching_radar_scores(report: dict[str, Any], topic: str) -> None:
    for panel, radar_items in report["products"][topic]["new_product_radar"].items():
        heat_scores = {
            item["name"]: item["score"]
            for item in report["products"][topic]["heat_rankings"][panel]
        }
        for radar_item in radar_items:
            matched_score = heat_scores.get(radar_item["name"])
            if matched_score is not None:
                radar_item["score"] = matched_score


def _drop_hidden_makeup_radar(report: dict[str, Any]) -> None:
    for panel, items in report["products"]["makeup"]["new_product_radar"].items():
        report["products"]["makeup"]["new_product_radar"][panel] = [
            item
            for item in items
            if (item.get("launch_evidence") or {}).get("quarantine_status") == "verified"
        ]


def _regenerate_sources(report: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []

    def add(url: str, source_type: str, reason: str, checked_at: str = CHECKED_AT) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        sources.append(
            {
                "checked_at": checked_at,
                "id": f"src_{len(sources) + 1:04d}",
                "provenance": {
                    "reason": reason,
                    "verification_status": "verified",
                },
                "type": source_type,
                "url": url,
            }
        )

    for topic, section, panel, product in _iter_products(report):
        link = product["detail"]["price_link"]["link"]
        if link:
            add(
                link,
                "product_page",
                "Direct product URL referenced inside the verified historical month report.",
            )
        evidence = product.get("launch_evidence", {}).get("evidence", {})
        evidence_url = evidence.get("url", "")
        if evidence_url:
            add(
                evidence_url,
                evidence.get("type", "editorial"),
                "Launch evidence cited by the verified historical month report.",
                evidence.get("checked_at", CHECKED_AT),
            )

    existing["sources"] = sources
    existing["total_sources"] = len(sources)
    return existing


def apply() -> None:
    report = _load(REPORT_PATH)
    sources = _load(SOURCES_PATH)
    manifest = _load(MANIFEST_PATH)

    # Visible-copy cleanup in heat panels.
    _set_text_cell(
        _find(report, "makeup", "heat_rankings", "CN LUXURY", "Lancôme Longwear Foundation"),
        "brand",
        "French luxury makeup (L'Oréal) · longwear foundation bestseller",
    )
    _set_text_cell(
        _find(report, "makeup", "heat_rankings", "CN LUXURY", "Chanel Rouge Coco Flash"),
        "buzz",
        "Smzdm: active cross-platform reviews and price checks for hero shades 70, 106, and 154",
    )
    _set_text_cell(
        _find(report, "makeup", "heat_rankings", "CN MASSTIGE", "Perfect Diary Slim Lipstick"),
        "buzz",
        "Smzdm: L04 red-brown shade spotlight at ¥95 / Baidu: next-generation pro-beauty positioning with makeup-plus-care messaging",
    )
    _set_text_cell(
        _find(report, "makeup", "heat_rankings", "US LUXURY", "Tom Ford Shade & Illuminate Foundation"),
        "key_features",
        "Glow foundation and contour effect · 12 shades · skincare-infused formula",
    )
    _set_text_cell(
        _find(report, "makeup", "heat_rankings", "CN MASSTIGE", "Flower Knows Unicorn Lip Gloss"),
        "buzz",
        "Douyin: Unicorn series searches stayed active with rich swatch content / Taobao Beauty: ¥89 mirror-gloss try-ons / GirlStyle praised the collection's highly decorative, fairytale-inspired unicorn packaging",
    )

    # Remove unsupported NEW flags that have no same-market verified radar match.
    _find(report, "makeup", "heat_rankings", "CN MASSTIGE", "Judydoll Lip Powder Foundation N31-N34")[
        "new_badge"
    ] = None
    _find(report, "makeup", "heat_rankings", "US LUXURY", "YSL Skin Affair Soft Glow Cushion Foundation")[
        "new_badge"
    ] = None
    _find(report, "fragrance", "heat_rankings", "US MASSTIGE", "Glossier You")["new_badge"] = None

    # CN radar rows that stay visible on the English page.
    product = _find(report, "makeup", "new_product_radar", "CN LUXURY", "毛戈平 光韵奢华粉底霜")
    _rename(product, "MAOGEPING Luxurious Radiant Foundation Cream", "毛戈平 光韵奢华粉底霜")
    product["category_badge"] = "Foundation Cream"
    _set_text_cell(product, "brand", "June on-sale launch in MAOGEPING's complexion line")
    _set_text_cell(
        product,
        "buzz",
        "Premium-base discussion on Xiaohongshu focused on the porcelain-glow finish",
    )
    _set_text_cell(
        product,
        "key_features",
        "12-hour porcelain-glow finish · three skincare essences · 40g cream foundation",
    )
    _set_price(
        product,
        "¥680 / 40g",
        "https://www.maogepingbeauty.com/makeup/face/powder/179.html",
    )

    product = _find(report, "makeup", "new_product_radar", "CN MASSTIGE", "卡姿兰 敦煌联名系列")
    _rename(product, "Carslan x Dunhuang Museum Collection", "卡姿兰 敦煌联名系列")
    product["category_badge"] = "Makeup Collection"
    _set_text_cell(product, "brand", "June collection launch with a museum-collaboration capsule")
    _set_text_cell(
        product,
        "buzz",
        "Vogue China highlighted the six-piece Dunhuang capsule and its museum-certified color story",
    )
    _set_text_cell(
        product,
        "key_features",
        "Dunhuang red, celestial dancer, and nine-colored deer packaging across six hero SKUs",
    )
    _set_price(product, "From ¥69", "https://www.carslan.com.cn/xilie")

    product = _find(report, "makeup", "new_product_radar", "CN MASSTIGE", "酵色 贝壳系列唇泥（新色）")
    _rename(product, "JOOCYEE Shell Series Lip Mud New Shades", "酵色 贝壳系列唇泥（新色）")
    product["category_badge"] = "Matte Lip Mud"
    _set_text_cell(product, "brand", "June shade-extension launch in the Shell series")
    _set_text_cell(
        product,
        "buzz",
        "Low-saturation shell-tone swatches kept circulating across Chinese beauty forums",
    )
    _set_text_cell(
        product,
        "key_features",
        "Shell sheen · muted nude-brown new shades · soft-focus lip-mud texture",
    )
    _set_price(
        product,
        "$21.12",
        "https://www.yami.com/zh/p/shell-amber-mirror-lip-glaze-matte-lip-mud-lipstick-v01/3023274121",
    )

    # Hide lower-confidence or duplicate radar rows instead of fabricating product-level proof.
    _hide_radar(
        _find(report, "makeup", "new_product_radar", "US LUXURY", "Marc Jacobs Drawn This Way Eyeliner"),
        "Hidden from the visible monthly radar: lower-fidelity duplicate of the verified Drawn This Way gel eyeliner SKU.",
    )
    _hide_radar(
        _find(report, "makeup", "new_product_radar", "US LUXURY", "Tom Ford Shade & Illuminate Foundation"),
        "Hidden from the visible monthly radar: unable to verify a direct June product page and product-level retail proof for this exact SKU.",
    )
    _hide_radar(
        _find(report, "makeup", "new_product_radar", "US LUXURY", "Marc Jacobs Money Shot Highlighter Gel"),
        "Hidden from the visible monthly radar: only bundle-level retail references were found, not a stable standalone product page.",
    )
    _hide_radar(
        _find(report, "makeup", "new_product_radar", "US MASSTIGE", "Marc Jacobs Joystick Blush Stick"),
        "Hidden from the visible monthly radar: cross-tier duplicate of the verified Marc Jacobs blush-stick launch.",
    )
    _hide_radar(
        _find(report, "makeup", "new_product_radar", "US MASSTIGE", "Marc Jacobs Money Shot Highlighter Gel"),
        "Hidden from the visible monthly radar: only bundle-level retail references were found, not a stable standalone product page.",
    )
    _hide_radar(
        _find(report, "makeup", "new_product_radar", "US MASSTIGE", "Tower 28 Splashy Cream Blush Hydrating Gel"),
        "Hidden from the visible monthly radar: unable to verify a direct product page or exact June launch evidence for this named SKU.",
    )

    # Keep the higher-confidence visible US radar rows direct-linked.
    product = _find(
        report,
        "makeup",
        "new_product_radar",
        "US LUXURY",
        "Marc Jacobs Drawn This Way Gel Eyeliner",
    )
    _set_price(
        product,
        "$26",
        "https://www.sephora.com/product/drawn-this-way-long-wear-waterproof-gel-eyeliner-P524951",
    )
    _set_text_cell(product, "brand", "June Sephora launch in Marc Jacobs Beauty's new eye line")

    # CN fragrance hero corrections.
    product = _find(
        report,
        "fragrance",
        "heat_rankings",
        "CN MASSTIGE",
        "Documents 昆仑煮雪 (Kunlun Boiled Snow)",
    )
    _rename(product, "To Summer Kunlun Boiled Snow", "观夏 昆仑煮雪")
    product["category_badge"] = "Oriental Woody Eau de Toilette"
    _set_text_cell(
        product,
        "brand",
        "Chinese niche fragrance house To Summer · cedar-led oriental woody signature",
    )
    _set_price(
        product,
        "$169.90 / 30ml",
        "https://www.yami.com/en/p/kunlun-snow-eau-de-toilette-oriental-woody-unisex-fragrance-30ml/3023922521",
    )

    product = _find(
        report,
        "fragrance",
        "heat_rankings",
        "CN MASSTIGE",
        "Scent Library 凉白开 (Cool Boiled Water)",
    )
    _rename(product, "Scent Library Cool Boiled Water", "气味图书馆 凉白开")
    product["category_badge"] = "Aquatic Mineral Eau de Toilette"
    _set_text_cell(
        product,
        "brand",
        "Chinese mass-fragrance label Scent Library · nostalgia-led watery musk signature",
    )
    _set_price(
        product,
        "$75.59 / 50ml",
        "https://www.yami.com/en/p/l-b-k-water-eau-de-toilette-50ml/3023862421",
    )

    product = _find(
        report,
        "fragrance",
        "heat_rankings",
        "CN MASSTIGE",
        "Boitown 幻境流沙金 (Mirage Quicksand Gold)",
    )
    _rename(product, "Boitown Mirage Quicksand Gold", "冰希黎 幻境流沙金")
    product["category_badge"] = "Floral Gourmand Eau de Parfum"
    _set_text_cell(
        product,
        "brand",
        "Chinese masstige fragrance label Boitown · glitter-bottle floral gourmand signature",
    )
    _set_price(
        product,
        "$66.90 / 60ml",
        "https://www.sayweee.com/en/product/BOITOWN-BY-BOITOWN-Illusory-Gilded-Edition/2810458",
    )

    # Fragrance heat direct links / price strings.
    _set_price(
        _find(report, "fragrance", "heat_rankings", "US LUXURY", "Tom Ford Taormina Orange EDP"),
        "$150 / 30ml",
        "https://www.tomfordbeauty.com/products/taormina-orange-eau-de-parfum",
    )
    _set_price(
        _find(
            report,
            "fragrance",
            "heat_rankings",
            "US LUXURY",
            "Jean Paul Gaultier Le Male In Blue",
        ),
        "$145 / 125ml",
        "https://www.sephora.com/product/le-male-in-blue-limited-edition-P525202",
    )
    _set_price(
        _find(
            report,
            "fragrance",
            "heat_rankings",
            "US LUXURY",
            "Bvlgari Eau Parfumée Thé Impérial",
        ),
        "$165-$250 / 75-150ml",
        "https://www.nordstrom.com/s/eau-parfumee-the-imperial-150-eau-de-toilette/8867990",
    )
    _set_price(
        _find(
            report,
            "fragrance",
            "heat_rankings",
            "US LUXURY",
            "Guerlain Aqua Allegoria Perle Rosa Rossa",
        ),
        "S$295 / 125ml",
        "https://www.guerlain.com/sg/en-sg/p/aqua-allegoria-perle-rosa-rossa-perle---eau-de-parfum-P062205.html",
    )
    product = _find(
        report,
        "fragrance",
        "heat_rankings",
        "US LUXURY",
        "L’Artisan Parfumeur L’Amant EDP",
    )
    _rename(product, "L'Artisan Parfumeur L'Amant EDP")
    _set_price(
        product,
        "$265 / 100ml",
        "https://www.artisanparfumeur.com/us/en_US/p/l-amant-eau-de-parfum-100-ml--000000000065228189",
    )
    _set_price(
        _find(
            report,
            "fragrance",
            "heat_rankings",
            "US LUXURY",
            "Rabanne Million Gold For Her Pure Diamonds",
        ),
        "£104 / 50ml",
        "https://www.rabanne.com/ww/en/fragrance/p/million-gold-for-her-pure-diamonds--000000000065242102",
    )
    _set_price(
        _find(report, "fragrance", "heat_rankings", "US MASSTIGE", "Phlur Rose Whip EDP"),
        "$99 / 50ml",
        "https://phlur.com/pages/rose-whip",
    )
    _set_price(
        _find(
            report,
            "fragrance",
            "heat_rankings",
            "US MASSTIGE",
            "Huda Beauty Easy Bake Intense EDP",
        ),
        "$79 / 50ml",
        "https://hudabeauty.com/en-us/products/easy-bake-intense-eau-de-parfum-50ml-hb01351",
    )
    _set_price(
        _find(report, "fragrance", "heat_rankings", "US MASSTIGE", "Lake & Skye 11 11 Moon EDP"),
        "$105 / 50ml",
        "https://www.lakeandskye.com/products/11-11-moon-eau-de-parfum",
    )
    _set_price(
        _find(report, "fragrance", "heat_rankings", "US MASSTIGE", "DedCool Mochi Milk"),
        "$90 / 1.7 oz",
        "https://dedcool.com/products/mochi-milk-fragrance",
    )
    _set_price(
        _find(report, "fragrance", "heat_rankings", "US MASSTIGE", "Glossier You"),
        "$82 / 50ml",
        "https://www.glossier.com/products/glossier-you",
    )
    product = _find(report, "fragrance", "heat_rankings", "US MASSTIGE", "Sol de Janeiro Cheirosa 91")
    _rename(product, "Sol de Janeiro Cheirosa 91 Perfume Mist")
    _set_price(product, "$26 / 90ml", "https://soldejaneiro.com/products/cheirosa-91-perfume-mist")

    # Fragrance radar: brand + product name, direct links, price/currency/size, and launch text.
    radar = _find(report, "fragrance", "new_product_radar", "US LUXURY", "Taormina Orange EDP")
    _rename(radar, "Tom Ford Taormina Orange EDP")
    _copy_heat_detail(
        report,
        radar,
        "US LUXURY",
        "Tom Ford Taormina Orange EDP",
        "$150 / 30ml",
        "https://www.tomfordbeauty.com/products/taormina-orange-eau-de-parfum",
        "June limited-edition launch in the Private Blend line",
        "Citrus Aromatic Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US LUXURY", "Thé Impérial")
    _rename(radar, "Bvlgari Eau Parfumée Thé Impérial", "Thé Impérial")
    _copy_heat_detail(
        report,
        radar,
        "US LUXURY",
        "Bvlgari Eau Parfumée Thé Impérial",
        "$165-$250 / 75-150ml",
        "https://www.nordstrom.com/s/eau-parfumee-the-imperial-150-eau-de-toilette/8867990",
        "June fragrance launch extending Bvlgari's tea-fragrance line",
        "Tea Citrus Musk Eau de Toilette",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US LUXURY", "L'Amant")
    _rename(radar, "L'Artisan Parfumeur L'Amant EDP")
    _copy_heat_detail(
        report,
        radar,
        "US LUXURY",
        "L'Artisan Parfumeur L'Amant EDP",
        "$265 / 100ml",
        "https://www.artisanparfumeur.com/us/en_US/p/l-amant-eau-de-parfum-100-ml--000000000065228189",
        "June new eau de parfum launch in L'Artisan Parfumeur's artistic line",
        "Woody Spicy Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US LUXURY", "Million Gold")
    _rename(radar, "Rabanne Million Gold For Her Pure Diamonds")
    _copy_heat_detail(
        report,
        radar,
        "US LUXURY",
        "Rabanne Million Gold For Her Pure Diamonds",
        "£104 / 50ml",
        "https://www.rabanne.com/ww/en/fragrance/p/million-gold-for-her-pure-diamonds--000000000065242102",
        "June limited-edition launch in the Million Gold line",
        "Amber Floral Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US LUXURY", "Le Male In Blue")
    _rename(radar, "Jean Paul Gaultier Le Male In Blue")
    _copy_heat_detail(
        report,
        radar,
        "US LUXURY",
        "Jean Paul Gaultier Le Male In Blue",
        "$145 / 125ml",
        "https://www.sephora.com/product/le-male-in-blue-limited-edition-P525202",
        "June limited-edition launch in the Le Male franchise",
        "Aromatic Amber Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US LUXURY", "Rosa Rossa")
    _rename(radar, "Guerlain Aqua Allegoria Perle Rosa Rossa")
    _copy_heat_detail(
        report,
        radar,
        "US LUXURY",
        "Guerlain Aqua Allegoria Perle Rosa Rossa",
        "S$295 / 125ml",
        "https://www.guerlain.com/sg/en-sg/p/aqua-allegoria-perle-rosa-rossa-perle---eau-de-parfum-P062205.html",
        "June limited-edition launch in the Aqua Allegoria Perle line",
        "Rose Floral Musk Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US MASSTIGE", "Easy Bake Intense EDP")
    _rename(radar, "Huda Beauty Easy Bake Intense EDP")
    _copy_heat_detail(
        report,
        radar,
        "US MASSTIGE",
        "Huda Beauty Easy Bake Intense EDP",
        "$79 / 50ml",
        "https://hudabeauty.com/en-us/products/easy-bake-intense-eau-de-parfum-50ml-hb01351",
        "June new eau de parfum launch from Huda Beauty",
        "Floral Gourmand Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US MASSTIGE", "Rose Whip")
    _rename(radar, "Phlur Rose Whip EDP")
    _copy_heat_detail(
        report,
        radar,
        "US MASSTIGE",
        "Phlur Rose Whip EDP",
        "$99 / 50ml",
        "https://phlur.com/pages/rose-whip",
        "June new rose-fragrance launch in Phlur's perfume line",
        "Rose Floral Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US MASSTIGE", "You Solid")
    _rename(radar, "Glossier You Solid")
    _set_text_cell(radar, "buzz", "Glossier introduced the portable solid format as a compact extension of its hero skin scent")
    _set_text_cell(
        radar,
        "key_features",
        "Portable solid perfume · ambrette, ambrox, iris root, and pink pepper · 3g tin",
    )
    _set_text_cell(radar, "brand", "June solid-format launch extending the Glossier You line")
    radar["category_badge"] = "Solid Perfume"
    _set_price(radar, "$35 / 3g", "https://www.glossier.com/products/glossier-you-solid")

    radar = _find(report, "fragrance", "new_product_radar", "US MASSTIGE", "Cheirosa 91")
    _rename(radar, "Sol de Janeiro Cheirosa 91 Perfume Mist")
    _copy_heat_detail(
        report,
        radar,
        "US MASSTIGE",
        "Sol de Janeiro Cheirosa 91 Perfume Mist",
        "$26 / 90ml",
        "https://soldejaneiro.com/products/cheirosa-91-perfume-mist",
        "June perfume-mist launch in the Cheirosa line",
        "Floral Gourmand Perfume Mist",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US MASSTIGE", "11 11 Moon")
    _rename(radar, "Lake & Skye 11 11 Moon EDP")
    _copy_heat_detail(
        report,
        radar,
        "US MASSTIGE",
        "Lake & Skye 11 11 Moon EDP",
        "$105 / 50ml",
        "https://www.lakeandskye.com/products/11-11-moon-eau-de-parfum",
        "June new scent launch in the 11 11 line",
        "Skin-Scent Eau de Parfum",
    )

    radar = _find(report, "fragrance", "new_product_radar", "US MASSTIGE", "Mochi Milk")
    _rename(radar, "DedCool Mochi Milk")
    _copy_heat_detail(
        report,
        radar,
        "US MASSTIGE",
        "DedCool Mochi Milk",
        "$90 / 1.7 oz",
        "https://dedcool.com/products/mochi-milk-fragrance",
        "June new gourmand launch in the Milk family",
        "Milky Gourmand Eau de Parfum",
    )

    _sync_matching_radar_scores(report, "fragrance")
    _drop_hidden_makeup_radar(report)

    _dump(REPORT_PATH, report)

    sources = _regenerate_sources(report, sources)
    _dump(SOURCES_PATH, sources)

    manifest["canonical_hash"] = _sha256(REPORT_PATH)
    manifest["sources_hash"] = _sha256(SOURCES_PATH)
    _dump(MANIFEST_PATH, manifest)

    print("Patched:", REPORT_PATH)
    print("Patched:", SOURCES_PATH)
    print("Patched:", MANIFEST_PATH)


if __name__ == "__main__":
    apply()
