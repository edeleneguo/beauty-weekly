# Beauty Weekly – Build Pipeline

Automated extract → render → validate pipeline for the ZURU EDGE Beauty Weekly reports.

## Architecture

```
archive/week-28/          ← Historical snapshots (immutable)
data/week28.json          ← Canonical structured data source
build/
  extract_data.py         ← Extracts product records from root HTML → data/week28.json
  render.py               ← Regenerates 4 root HTML files from data/week28.json
  validate.py             ← Cross-check validator (IT rules)
  verify_deploy.sh        ← Deployment hash verification
.github/workflows/ci.yml  ← CI: extract → render → validate → lint → drift check
```

## Quick Start

```bash
python3 build/extract_data.py   # Extract → data/week28.json
python3 build/render.py         # Render → 4 root HTML files
python3 build/validate.py       # Validate all rules
python3 -m pytest tests/ -v     # Run regression tests
```

## Data Flow

```
Root HTML (source of truth)
    ↓  extract_data.py
data/week28.json (canonical)
    ↓  render.py
Root HTML (regenerated, deterministic)
```

One edit in `data/week28.json` propagates to all 4 language/topic variants.

## Validation Rules

| Rule | Description |
|------|-------------|
| panel-count | Exactly 4 panels per section (US/CN × LUXURY/MASSTIGE) |
| panel-rows | Exactly 10 products per heat panel; dynamic (0-10) for radar |
| score-range | All scores between 65 and 98 |
| rank-range | All ranks between 1 and 10 |
| duplicate-ranks | No duplicate ranks within a panel |
| cross-section-consistency | Same product has same score in Heat and Radar |
| trend-tags-missing | Trend-badge products must have concrete trend_tags |
| language-purity | EN files use lang="en", CN files use lang="zh-CN" |
| forbidden-phrases | No "undefined", "null", "TODO", etc. |
| edp-spacing | "EDP" must have a space before it |
| href-policy | All product links use target="_blank" |
| evidence-urls | No placeholder URLs (example.com, localhost) |
| trend-badge-value | Trend badges are "Trend" or null |
| new-badge-value | New badges are "New"/"NEW" or null |
| score-label-count | Exactly 4 score labels per Section 03, 0 in Section 04 |
| item-count | Exactly 40 items in Section 03; dynamic in Section 04 |

## CI

The GitHub Actions workflow runs on every push/PR:
1. Extract canonical data
2. Render HTML from data
3. Validate all rules
4. Run regression tests (pytest)
5. Lint with ruff
6. Verify no uncommitted drift (build output must match git state)
