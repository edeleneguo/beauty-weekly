#!/usr/bin/env python3
"""Fix all data defects in data/week28.json.

Changes:
1. Add concrete trend_tags to key_features for every trend-badge product
2. Fix language leakage: Chinese text in EN fields of radar products
3. Fix identical EN/CN key_features in heat products (add CN translations)
4. Fix data copy-paste errors (Le Labo, To Summer)
5. Remove all placeholder products from new_product_radar
6. Add name_cn for Chinese-origin brands
7. Fix YSL Skin Affair malformed key_features
"""

import json
import os
import copy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "week28.json")

# ── Trend tags: concrete qualifying tags for each trend-badge product ──
# Format: (topic, section, panel, product_name, tag_en, tag_cn)
TREND_TAGS = [
    # Makeup heat
    (
        "makeup",
        "heat_rankings",
        "US LUXURY",
        "YSL Skin Affair Soft Glow Cushion Foundation",
        "Skincare Foundation",
        "养肤粉底",
    ),
    (
        "makeup",
        "heat_rankings",
        "US LUXURY",
        "Westman Atelier Vital Skin Foundation",
        "Clean Beauty",
        "纯净美妆",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "Rare Beauty Find Comfort Tinted Moisturizer",
        "Tinted Moisturizer",
        "有色面霜",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "Fenty Beauty Gloss Bomb",
        "Lip Gloss Revival",
        "唇彩复兴",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "NYX Professional Fat Oil Lip Drip",
        "Lip Oil",
        "唇油",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "Kosas Cloud Set Blurring Powder",
        "Clean Powder",
        "纯净定妆",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN LUXURY",
        "LA MER Soft Fluid Long Wear Cushion",
        "Skincare Cushion",
        "养肤气垫",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN LUXURY",
        "Helena Rubinstein Powercell Foundation",
        "Skincare Foundation",
        "养肤粉底",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN MASSTIGE",
        "Judydoll Blush Palette",
        "Low Saturation",
        "低饱和",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN MASSTIGE",
        "Judydoll Lip Powder Foundation N31-N34",
        "Lip Powder",
        "唇粉",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN MASSTIGE",
        "3CE Nine-Pan Eyeshadow Palette",
        "Nine-Pan Palette",
        "九宫格",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN MASSTIGE",
        "Flower Knows Unicorn Lip Gloss",
        "Unicorn IP",
        "独角兽IP",
    ),
    # Fragrance heat
    (
        "fragrance",
        "heat_rankings",
        "US LUXURY",
        "Maison Margiela Replica Lazy Sunday Morning",
        "Lazy Sunday",
        "慵懒周日",
    ),
    (
        "fragrance",
        "heat_rankings",
        "US MASSTIGE",
        "Phlur Missing Person",
        "Skin Scent",
        "肌肤香",
    ),
    (
        "fragrance",
        "heat_rankings",
        "US MASSTIGE",
        "Kayali Freedom Musk Matcha",
        "Gourmand Matcha",
        "美食调抹茶",
    ),
    (
        "fragrance",
        "heat_rankings",
        "US MASSTIGE",
        "DedCool Mochi Milk",
        "Milky Scent",
        "奶香",
    ),
    (
        "fragrance",
        "heat_rankings",
        "US MASSTIGE",
        "Glossier You",
        "Skin Scent",
        "肌肤香",
    ),
    (
        "fragrance",
        "heat_rankings",
        "US MASSTIGE",
        "Lake & Skye 11 11 Moon EDP",
        "Moon Theme",
        "月光主题",
    ),
    (
        "fragrance",
        "heat_rankings",
        "US MASSTIGE",
        "Phlur Rose Whip EDP",
        "Rose Revival",
        "玫瑰复兴",
    ),
    (
        "fragrance",
        "heat_rankings",
        "CN LUXURY",
        "Le Labo Thé Matcha 26",
        "Tea Scent",
        "茶香",
    ),
    (
        "fragrance",
        "heat_rankings",
        "CN LUXURY",
        "Maison Margiela Lazy Weekend",
        "Pseudo Body Scent",
        "伪体香",
    ),
    (
        "fragrance",
        "heat_rankings",
        "CN MASSTIGE",
        "To Summer Kunlun Snow",
        "Chinese Niche",
        "国货小众",
    ),
    (
        "fragrance",
        "heat_rankings",
        "CN MASSTIGE",
        "Scent Library Boiled Water",
        "Chinese Nostalgic",
        "国货记忆",
    ),
    (
        "fragrance",
        "heat_rankings",
        "CN MASSTIGE",
        "Bingxili Mirage Quicksand Gold",
        "C-beauty Floral",
        "国货花果",
    ),
    # Fragrance radar (only one with trend_badge)
    (
        "fragrance",
        "new_product_radar",
        "US MASSTIGE",
        "DedCool Mochi Milk",
        "Milky Scent",
        "奶香",
    ),
]

# ── CN translations for heat products with identical EN/CN key_features ──
# Format: (topic, section, panel, product_name, key, cn_value)
HEAT_CN_FIXES = [
    (
        "makeup",
        "heat_rankings",
        "US LUXURY",
        "YSL Skin Affair Soft Glow Cushion Foundation",
        "key_features",
        "养肤粉底趋势 · 31色号 · 角鲨烷+聚谷氨酸 · 24H保湿",
    ),
    (
        "makeup",
        "heat_rankings",
        "US LUXURY",
        "Westman Atelier Vital Skin Foundation",
        "key_features",
        "纯净美妆 · 角鲨烷+椰子油 · 中等遮瑕",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "Rare Beauty Find Comfort Tinted Moisturizer",
        "key_features",
        "有色面霜 · 轻薄遮瑕 · 护肤成分",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "Fenty Beauty Gloss Bomb",
        "key_features",
        "高光泽 · 不粘腻 · 多色号",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "NYX Professional Fat Oil Lip Drip",
        "key_features",
        "高光泽 · 滋润 · 8色号",
    ),
    (
        "makeup",
        "heat_rankings",
        "US MASSTIGE",
        "Kosas Cloud Set Blurring Powder",
        "key_features",
        "无滑石粉 · 护肤级配方 · 柔焦效果",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN LUXURY",
        "LA MER Soft Fluid Long Wear Cushion",
        "key_features",
        "养肤气垫 · 双核芯 · SPF30 · 10色号",
    ),
    (
        "makeup",
        "heat_rankings",
        "CN LUXURY",
        "Helena Rubinstein Powercell Foundation",
        "key_features",
        "养肤粉底 · Powercell系列 · 修护成分",
    ),
]

# ── Data error fixes ──
# YSL Skin Affair: "Skincare Foundation Trend31 shades" → fix spacing
DATA_ERROR_FIXES = [
    (
        "makeup",
        "heat_rankings",
        "US LUXURY",
        "YSL Skin Affair Soft Glow Cushion Foundation",
        "key_features",
        "en",
        "Skincare Foundation Trend · 31 shades · Squalane + polyglutamic acid · 24H hydration",
    ),
]

# Le Labo Thé Matcha 26: currently has DedCool Mochi Milk's data
LE_LABO_FIX = {
    "key_features": {
        "en": "Matcha + green tea + musk · Unisex · Thé series newcomer",
        "cn": "抹茶+绿茶+麝香 · 无性别 · Thé系列新作",
    },
    "buzz": {
        "en": "Fragrantica newcomer · Tea fragrance revival wave",
        "cn": "Fragrantica新作 · 茶香复兴浪潮",
    },
    "brand": {
        "en": "French niche (Estée Lauder) · Tea-themed fragrance",
        "cn": "法国小众（Estée Lauder旗下） · 茶香主题",
    },
}

# To Summer Kunlun Snow: currently has Maison Margiela Lazy Weekend's data
TO_SUMMER_FIX = {
    "key_features": {
        "en": "Skin musk · Kunlun snow narrative · Chinese niche storytelling",
        "cn": "肌肤感麝香 · 昆仑雪叙事 · 国货小众故事香",
    },
    "buzz": {
        "en": "Douyin pseudo-body-scent topic · C-beauty niche discovery",
        "cn": "抖音伪体香话题 · 国货小众发现",
    },
    "brand": {
        "en": "Chinese niche (To Summer) · Nature narrative EDP",
        "cn": "中国小众（观夏） · 自然叙事香水",
    },
}

# ── Chinese brand name mappings (EN name → CN name for CN pages) ──
CN_BRAND_NAMES = {
    "Judydoll Blush Palette": "橘朵腮红盘",
    "Judydoll Lip Powder Foundation N31-N34": "橘朵唇粉底霜 N31-N34",
    "3CE Nine-Pan Eyeshadow Palette": "3CE九宫格眼影盘",
    "Flower Knows Unicorn Lip Gloss": "花知晓独角兽唇釉",
    "Mao Geping Light Sculpting Foundation": "毛戈平光影塑形粉底液",
    "To Summer Kunlun Snow": "观夏昆仑雪",
    "Scent Library Boiled Water": "气味图书馆凉白开",
    "Bingxili Mirage Quicksand Gold": "冰希黎流沙金",
}

# ── Radar product EN translations (Chinese text currently in EN fields) ──
# Format: (topic, panel, product_name, field_key, en_value)
RADAR_EN_FIXES = [
    # US LUXURY makeup
    (
        "makeup",
        "US LUXURY",
        "NARS Light Reflecting Foundation (expanded shades)",
        "key_features",
        "Expanded shade range · Skincare ingredients · Radiant finish",
    ),
    (
        "makeup",
        "US LUXURY",
        "NARS Light Reflecting Foundation (expanded shades)",
        "brand",
        "2026 · Radiant foundation benchmark · Shade expansion",
    ),
    (
        "makeup",
        "US LUXURY",
        "Ogee Sculpted Complexion Stick",
        "key_features",
        "NSF Certified Organic · Multi-use · 6/22 Sephora launch",
    ),
    (
        "makeup",
        "US LUXURY",
        "Ogee Sculpted Complexion Stick",
        "buzz",
        "Ulta 6,084 reviews 4.7/5 · One sold every 38 seconds",
    ),
    (
        "makeup",
        "US LUXURY",
        "Ogee Sculpted Complexion Stick",
        "brand",
        "2026.6.22 · Sephora new launch · Clean Beauty luxury",
    ),
    (
        "makeup",
        "US LUXURY",
        "CHANEL Rouge Coco Hydra Gloss",
        "key_features",
        "85% hydrating base · Camellia ceramide · 18 shades",
    ),
    (
        "makeup",
        "US LUXURY",
        "CHANEL Rouge Coco Hydra Gloss",
        "buzz",
        "The Beauty Look Book / Allure editor preview positive",
    ),
    (
        "makeup",
        "US LUXURY",
        "CHANEL Rouge Coco Hydra Gloss",
        "brand",
        "2026.6 Summer collection · Rouge Coco Gloss formula upgrade",
    ),
    (
        "makeup",
        "US LUXURY",
        "Rare Beauty Find Comfort Tinted Moisturizer",
        "key_features",
        "Tinted moisturizer · Skincare base · Multiple shades",
    ),
    (
        "makeup",
        "US LUXURY",
        "Rare Beauty Find Comfort Tinted Moisturizer",
        "brand",
        "2026 · Find Comfort line · Skincare base makeup",
    ),
    (
        "makeup",
        "US LUXURY",
        "Tom Ford Shade & Illuminate Soft Radiance",
        "key_features",
        "Glow base + contour in one · 12 shades",
    ),
    (
        "makeup",
        "US LUXURY",
        "Tom Ford Shade & Illuminate Soft Radiance",
        "buzz",
        "Saks: SPF50 medium coverage glow foundation",
    ),
    (
        "makeup",
        "US LUXURY",
        "Tom Ford Shade & Illuminate Soft Radiance",
        "brand",
        "2026 · Shade & Illuminate line extension",
    ),
    # US MASSTIGE makeup
    (
        "makeup",
        "US MASSTIGE",
        "Saie Dew Blush",
        "key_features",
        "12 shades · Sheer natural · Clean Girl aesthetic",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "Saie Dew Blush",
        "brand",
        "2026 · Liquid blush benchmark",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "e.l.f. Thirst Burst Lip Treatment",
        "key_features",
        "1% peptide complex · 12h hydration · 3 shades",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "e.l.f. Thirst Burst Lip Treatment",
        "buzz",
        "e.l.f. official 4.3/5",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "e.l.f. Thirst Burst Lip Treatment",
        "brand",
        "2026.6 · Entirely new product line",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "Tower 28 Splashy Hydrosilica Lip Gloss",
        "key_features",
        "Watery texture · Clean formula · Natural flush",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "Tower 28 Splashy Hydrosilica Lip Gloss",
        "buzz",
        "Allure: Sensitive skin makeup benchmark",
    ),
    (
        "makeup",
        "US MASSTIGE",
        "Tower 28 Splashy Hydrosilica Lip Gloss",
        "brand",
        "2026 · Splashy line extension",
    ),
    # CN MASSTIGE makeup
    (
        "makeup",
        "CN MASSTIGE",
        "橘朵 Lip Powder Foundation N31-N34新色",
        "key_features",
        "Matte finish · High pigment · 4 new shades",
    ),
    (
        "makeup",
        "CN MASSTIGE",
        "橘朵 Lip Powder Foundation N31-N34新色",
        "buzz",
        "Cumulative sales 10.24M · Douyin hashtag",
    ),
    (
        "makeup",
        "CN MASSTIGE",
        "橘朵 Lip Powder Foundation N31-N34新色",
        "brand",
        "2026.5 · Existing Lip Powder Foundation line new shades",
    ),
    (
        "makeup",
        "CN MASSTIGE",
        "花西子 好气色粉底液",
        "key_features",
        "Oriental floral essence · Skincare base · Trial pack monthly 40K+",
    ),
    (
        "makeup",
        "CN MASSTIGE",
        "花西子 好气色粉底液",
        "buzz",
        "Tmall monthly 40K+ · Cushion 30-day sales 200K+",
    ),
    (
        "makeup",
        "CN MASSTIGE",
        "花西子 好气色粉底液",
        "brand",
        "2026 · Good Complexion base makeup line new product",
    ),
    # US LUXURY fragrance
    (
        "fragrance",
        "US LUXURY",
        "D&G Your Devotion EDP Intense",
        "key_features",
        "Sicilian melon + orange blossom + vanilla milk · Olivier Cresp",
    ),
    (
        "fragrance",
        "US LUXURY",
        "D&G Your Devotion EDP Intense",
        "buzz",
        "Fragrantica 4.26/5 · 2026 new launch",
    ),
    (
        "fragrance",
        "US LUXURY",
        "D&G Your Devotion EDP Intense",
        "brand",
        "2026 · D&G new fragrance · Floral Gourmand",
    ),
    (
        "fragrance",
        "US LUXURY",
        "KAYALI Boujee Kitty Caramel Milk 22",
        "key_features",
        "Caramel milk + salted caramel + white chocolate · 50ml",
    ),
    (
        "fragrance",
        "US LUXURY",
        "KAYALI Boujee Kitty Caramel Milk 22",
        "buzz",
        "KAYALI July 25 global launch · Gourmand new work",
    ),
    (
        "fragrance",
        "US LUXURY",
        "KAYALI Boujee Kitty Caramel Milk 22",
        "brand",
        "2026.7.25 · KAYALI new fragrance",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Tom Ford Taormina Orange EDP",
        "key_features",
        "Neroli + Sicilian blood orange + oakmoss · Summer limited",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Tom Ford Taormina Orange EDP",
        "buzz",
        "Fragrantica 4.04/5 (313 votes)",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Bvlgari Eau Parfumée Thé Impérial",
        "key_features",
        "Sri Lankan black tea + Italian citrus + musk · Tea culture theme",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Bvlgari Eau Parfumée Thé Impérial",
        "buzz",
        "Harper's Bazaar editor deep positive review",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Bvlgari Eau Parfumée Thé Impérial",
        "brand",
        "2026 · Tea culture theme",
    ),
    (
        "fragrance",
        "US LUXURY",
        "L\u2019Artisan Parfumeur L\u2019Amant EDP",
        "key_features",
        "Patchouli + woody + warm spice · Nathalie Lorson",
    ),
    (
        "fragrance",
        "US LUXURY",
        "L\u2019Artisan Parfumeur L\u2019Amant EDP",
        "buzz",
        "Now Smell This: Rich patchouli seduction story",
    ),
    (
        "fragrance",
        "US LUXURY",
        "L\u2019Artisan Parfumeur L\u2019Amant EDP",
        "brand",
        "2026 · Woody spicy",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Guerlain Aqua Allegoria Perle Rosa Rossa",
        "key_features",
        "Rose water + peony + creamy sandalwood · Limited edition",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Guerlain Aqua Allegoria Perle Rosa Rossa",
        "buzz",
        "Fragrantica: Dewy rose sensual freshness",
    ),
    (
        "fragrance",
        "US LUXURY",
        "Guerlain Aqua Allegoria Perle Rosa Rossa",
        "brand",
        "2026 · Aqua Allegoria rose revival",
    ),
    # US MASSTIGE fragrance
    (
        "fragrance",
        "US MASSTIGE",
        "Sol de Janeiro Cheirosa 91 Rosa Charmosa",
        "key_features",
        "Passion fruit + honey caramel + Rio pink rose · Body Mist format",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "Sol de Janeiro Cheirosa 91 Rosa Charmosa",
        "buzz",
        "FarawayPlaces: Launch day review · 2026 new product",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "Sol de Janeiro Cheirosa 91 Rosa Charmosa",
        "brand",
        "2026 · Body Mist format · Rose revival",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "DedCool Mochi Milk",
        "key_features",
        "Marshmallow + peach + incense · Clean Gourmand",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "DedCool Mochi Milk",
        "brand",
        "2025 · Clean Gourmand · Layering benchmark",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "Glossier You Solid",
        "key_features",
        "White musk + ambrette + iris · Alcohol-free wax base",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "Glossier You Solid",
        "buzz",
        "Cosmopolitan 2026: Solid fragrance innovation",
    ),
    (
        "fragrance",
        "US MASSTIGE",
        "Glossier You Solid",
        "brand",
        "Solid format 2026 trend · Skin scent solid version",
    ),
]


def _find_product(products, name):
    """Find a product by name in a list."""
    for p in products:
        if p.get("name") == name:
            return p
    return None


def fix_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    for topic in ("makeup", "fragrance"):
        # ── Fix heat_rankings ──
        heat = data["products"][topic].get("heat_rankings", {})
        for panel_key, products in heat.items():
            for p in products:
                name = p.get("name", "")
                detail = p.get("detail", {})

                # 1. Add trend_tags to key_features for trend-badge products
                for t in TREND_TAGS:
                    if t[0] == topic and t[2] == panel_key and t[3] == name:
                        kf = detail.get("key_features", {})
                        kf["trend_tags"] = [t[4]]
                        kf["trend_tags_cn"] = [t[5]]
                        detail["key_features"] = kf
                        break

                # 2. Fix CN translations for identical EN/CN key_features
                for fix in HEAT_CN_FIXES:
                    if (
                        fix[0] == topic
                        and fix[2] == panel_key
                        and fix[3] == name
                        and fix[4] in detail
                    ):
                        detail[fix[4]]["cn"] = fix[5]
                        break

                # 3. Fix data errors
                for fix in DATA_ERROR_FIXES:
                    if fix[0] == topic and fix[2] == panel_key and fix[3] == name:
                        cell = detail.get(fix[4], {})
                        cell[fix[5]] = fix[6]
                        detail[fix[4]] = cell
                        break

                # 4. Fix Le Labo Thé Matcha 26
                if topic == "fragrance" and name == "Le Labo Thé Matcha 26":
                    for key, vals in LE_LABO_FIX.items():
                        if key in detail:
                            detail[key].update(vals)

                # 5. Fix To Summer Kunlun Snow
                if topic == "fragrance" and name == "To Summer Kunlun Snow":
                    for key, vals in TO_SUMMER_FIX.items():
                        if key in detail:
                            detail[key].update(vals)

                # 6. Add name_cn for Chinese brands
                if name in CN_BRAND_NAMES:
                    p["name_cn"] = CN_BRAND_NAMES[name]

                p["detail"] = detail

        # ── Fix new_product_radar ──
        radar = data["products"][topic].get("new_product_radar", {})
        for panel_key in list(radar.keys()):
            products = radar[panel_key]
            # Remove all placeholder products (score == 0)
            real_products = [p for p in products if p.get("score", 0) > 0]
            radar[panel_key] = real_products

            for p in real_products:
                name = p.get("name", "")
                detail = p.get("detail", {})

                # Add trend_tags for DedCool Mochi Milk (only radar product with trend_badge)
                if p.get("trend_badge") == "Trend" and name == "DedCool Mochi Milk":
                    kf = detail.get("key_features", {})
                    kf["trend_tags"] = ["Milky Scent"]
                    kf["trend_tags_cn"] = ["奶香"]
                    detail["key_features"] = kf

                # Fix EN language leakage
                for fix in RADAR_EN_FIXES:
                    if fix[0] == topic and fix[1] == panel_key and fix[2] == name:
                        if fix[3] in detail:
                            detail[fix[3]]["en"] = fix[4]

                # Add name_cn for Chinese brands in radar
                if name in CN_BRAND_NAMES:
                    p["name_cn"] = CN_BRAND_NAMES[name]

                p["detail"] = detail

    # Update version
    data["version"] = "week28-v2"
    data["version_en_makeup"] = "week28-en-20260713-v2"
    data["version_cn_makeup"] = "week28-cn-20260713-v2"
    data["version_en_fragrance"] = "week28-fragrance-en-20260713-v2"
    data["version_cn_fragrance"] = "week28-fragrance-cn-20260713-v2"

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)

    # Verify
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        check = json.load(f)

    print("=== Verification ===")
    for topic in ("makeup", "fragrance"):
        heat = check["products"][topic].get("heat_rankings", {})
        radar = check["products"][topic].get("new_product_radar", {})

        # Count trend_tags
        trend_count = 0
        for panel, products in heat.items():
            for p in products:
                if p.get("trend_badge"):
                    kf = p.get("detail", {}).get("key_features", {})
                    if "trend_tags" in kf:
                        trend_count += 1
                    else:
                        print(f"  MISSING trend_tags: {topic}/heat/{panel}/{p['name']}")
        for panel, products in radar.items():
            for p in products:
                if p.get("trend_badge"):
                    kf = p.get("detail", {}).get("key_features", {})
                    if "trend_tags" in kf:
                        trend_count += 1
        print(f"  {topic}: {trend_count} products with trend_tags")

        # Count radar products (should be dynamic, no placeholders)
        for panel, products in radar.items():
            real = len(products)
            print(f"  {topic}/radar/{panel}: {real} real products (no placeholders)")

        # Check for Chinese in EN fields of radar
        leakage = 0
        for panel, products in radar.items():
            for p in products:
                for key in ("price_link", "key_features", "buzz", "brand"):
                    cell = p.get("detail", {}).get(key, {})
                    en_val = cell.get("en", "")
                    has_cn = any("\u4e00" <= c <= "\u9fff" for c in en_val)
                    if has_cn:
                        leakage += 1
                        print(f"  LEAKAGE: {topic}/radar/{panel}/{p['name']}: {key}.en")
        print(f"  {topic}: {leakage} remaining EN field leakages in radar")

    print("\nDone. Run build/render.py and build/validate.py to verify.")


if __name__ == "__main__":
    fix_data()
