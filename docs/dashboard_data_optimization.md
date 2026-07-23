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

### CN New-Product Coverage

CN makeup and fragrance use category-specific discovery queries and brand-level searches.
The monthly collector bounds every query to the target calendar month and keeps the
discovery audit in `raw_collected.json`.

Generation uses two passes:

1. Broad discovery produces candidate products from monthly articles and brand searches.
2. Candidate verification searches unsupported CN radar names again and retains only
   products with matching launch evidence.

Google News URLs are discovery-only. The collector decodes them to the publisher's
direct URL, fetches structured page metadata when available, and rejects unresolved
aggregator URLs as publishable product evidence.

Coverage targets are soft health checks, not publication quotas:

- CN makeup radar: 8 verified products
- CN fragrance radar: 4 verified products

Falling below a soft floor triggers another discovery pass and is recorded as
`below_soft_floor`. It never pads a ranking with unsupported products.

Launch evidence is graded:

- A: official launch or dated official product listing
- B: dated retailer listing or reputable editorial evidence
- C: dated credible discovery or social-commerce evidence

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
