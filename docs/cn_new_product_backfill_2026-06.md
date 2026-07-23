# CN New-Product Backfill Audit - 2026-06

## Result

The evidence-reviewed backfill was applied to the June report on 2026-07-23.
It raised the CN new-product radar from 3 to 8 makeup products and from 0 to
6 fragrance products.

The soft floor remains a discovery trigger rather than a quota. Products were
added only when a June 2026 Mainland China launch, listing, preorder, preview,
or credible first verified mention could be tied to the named product.

## Approved Products

| Topic | Product | Evidence grade | Date basis |
| --- | --- | --- | --- |
| Makeup | Dior Rouge Dior Couture Color Lip Collection | B | Source publication |
| Makeup | INTO YOU Floating Airy Lip Mud 3.0 | B | Source publication |
| Makeup | RED CHAMBER Zhiheng Foundation | B | Source publication |
| Makeup | RIBECS Caviar Glow Flawless Cushion | C | First verified mention |
| Makeup | Pixian Douban Heritage Lipstick | B | Source publication |
| Fragrance | Dior Sauvage Extrait | B | Source publication |
| Fragrance | Dior Paradise Eau de Parfum | B | Source publication |
| Fragrance | DOCUMENTS Homeland City-Limited Extrait Collection | B | First listing |
| Fragrance | To Summer x Isabel Marant Blue Heat | B | Source publication |
| Fragrance | Cloud AiYang Four Seasons Collection | B | Source publication |
| Fragrance | Love and Deepspace Caleb Midsummer Fruit | A | First listing |

When a verified launch did not disclose price or size, the dashboard states
that the price and size are not publicly disclosed. Known verified prices are
retained. This makes the product signal useful without inventing commercial
data.

## Excluded Candidates

- Reimagined Miss Dior: the source did not expose a sufficiently exact SKU.
- Dries Van Noten and r.e.m. beauty: Mainland China availability was not verified.
- HOURGLASS Veil lipstick: the verified launch fell in July.
- Flower Knows Unicorn products: the available evidence was only a personal swatch.
- Acqua di Parma La Caletta: evidence covered Greater China, not Mainland China.
- BEAST candidate: the direct article did not expose an exact publication date.

## Reproducibility

The reviewed records and rejected candidates are stored in
`data/months/2026-06/cn_radar_backfill.json`. Run:

```bash
python3 build/apply_cn_radar_backfill.py --month 2026-06
BEAUTY_MONTHLY_MONTH=2026-06 ./build/monthly_update.sh
```

The pre-backfill rollback commit is
`3315fd8357ee44a652344390098cfaa442aff6ac`.
