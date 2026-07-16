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
  check.sh                 ← Single fail-closed local/CI quality gate
  check_secrets.py        ← Scans tracked and untracked repository files
  verify_deploy.sh        ← Deployment hash verification
.github/workflows/ci.yml  ← CI: secrets → lint → tests → validate → deterministic render
```

## Quick Start

```bash
pip install -r requirements-dev.txt
./build/check.sh                # Required before commit/push
./build/verify_deploy.sh        # Required after Pages deployment
```

## Data Flow

```
data/week28.json (canonical source of truth)
    ↓  render.py
Root HTML (regenerated, deterministic)
```

One edit in `data/week28.json` propagates to all 4 language/topic variants.
`extract_data.py` is a legacy migration utility, not the normal production entry point.

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
1. Scan tracked and untracked repository files for GitHub PAT patterns
2. Lint Python with ruff
3. Run regression tests (pytest)
4. Validate business and HTML rules
5. Render twice and compare complete SHA256 hashes
6. Verify generated files match the committed HTML exactly

Any missing tool, failed check, output drift, or validation error stops CI.
