# Dashboard Data Optimization Plan

This branch keeps the locked June 2026 dashboard release unchanged while adding the next data-quality layer for review.

## Score Explainability

The visible Heat Score should be explained with four stable business weights:

- Sales Momentum: 40%
- Buzz Momentum: 30%
- Review / Rating: 20%
- Trend Fit: 10%

For historical June 2026 data, the new breakdown is a display allocation over the existing score, not a raw recomputation. The dashboard now records `recomputable: false` until normalized sales, social, review, and trend-fit time-series are collected.

## Source Layers

Use three source layers instead of treating all links equally:

- Product layer: official product pages, retailer PDPs, brand Tmall/JD/Douyin product pages, Sephora/Ulta/department-store PDPs.
- Evidence layer: launch articles, editor roundups, RSS/news results, historical repo snapshots, and official campaign pages when a direct PDP is unavailable or unstable.
- Signal layer: monthly bestseller lists, review counts, rating snapshots, social/RSS volume, creator/editor mentions, and search/news freshness.

## Collection Strategy

RSS should stay as the broad discovery layer because it is stable and cheap. Crawlers should be narrower and evidence-led:

- Crawl only whitelisted domains and specific product/evidence URLs.
- Cache fetched pages with timestamps and source metadata.
- Respect robots.txt, rate limits, and retry budgets.
- Prefer structured data, RSS metadata, and platform APIs when available.
- Store raw signal snapshots separately from the curated report so scores can become recomputable later.

## Quality Gates

The audit should be reasonable rather than overly tight:

- Direct product links are preferred, but explicit evidence links are allowed when visible copy says the link is evidence-backed.
- Empty visible fields, rank disorder, generic storefront URLs, and missing score breakdowns are blocking issues.
- Lower coverage is allowed when it is disclosed through `data_quality`, not silently hidden.

## Next Owner Priorities

1. Build normalized raw-signal tables for sales, buzz, reviews, and trend tags.
2. Convert Heat Score from display allocation to true recomputation once each panel has sufficient raw coverage.
3. Add freshness windows per source type so stale evidence is visible in the dashboard.
4. Expand evidence richness without padding rankings or inventing unsupported products.
