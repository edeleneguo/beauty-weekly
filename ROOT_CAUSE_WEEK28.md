# ROOT CAUSE – Week 28 Inconsistencies

## Problem

Week 28 reports had **four independent HTML files** (index.html, index-cn.html,
fragrance.html, fragrance-cn.html) each hand-authored with no shared data source.
This led to:

1. **Cross-language product drift** – EN and CN versions of the same report had
   different product selections, scores, and ranks for the same market/tier panels.

2. **No single source of truth** – Editing a product in one file required manually
   propagating the change to three other files, leading to omissions and mismatches.

3. **Score/rank misalignment** – Same product appearing in both Heat Rankings and
   New Product Radar could have different scores across the two sections.

4. **Missing validation** – No automated checks for panel count, row count, score
   range, badge semantics, language purity, or terminology rules.

## Root Cause

The absence of a structured data layer between editorial input and HTML output.
Each HTML file was both the data source and the presentation layer, making
consistency enforcement manual and error-prone.

## Fix: Repair Architecture

Introduced a **canonical JSON data source** (`data/week28.json`) that serves as
the single source of truth for all product records across all four HTML files.

### Data Flow (Before)
```
Editor → index.html
Editor → index-cn.html
Editor → fragrance.html
Editor → fragrance-cn.html
(No cross-checks)
```

### Data Flow (After)
```
Editor → data/week28.json → render.py → 4 HTML files
                              ↓
                          validate.py (15+ rules)
```

### Key Design Decisions

1. **Canonical JSON stores language pairs** – Each product record has
   `{en: "...", cn: "..."}` for detail cell values, so one edit propagates
   to all language variants.

2. **No global split/join mutation** – Each product is processed independently.
   The extractor reads HTML, the renderer writes HTML. No shared mutable state.

3. **Deterministic rendering** – Same JSON + same templates = identical HTML.
   This enables CI drift detection.

4. **Preservation of non-data content** – Banner, news, trends, appendix, CSS,
   and JS are preserved verbatim from the original HTML templates.

### Files Changed
- `build/extract_data.py` – Rewritten to produce canonical JSON
- `build/render.py` – New deterministic renderer
- `build/validate.py` – New comprehensive validator
- `data/week28.json` – New canonical data source
- `.github/workflows/ci.yml` – New CI pipeline
- `build/verify_deploy.sh` – New deployment verification
- `README.md` – New documentation
