# Beauty Weekly Monthly Pipeline Recovery Design

## Objective

Restore Beauty Weekly as a reliable, English-first monthly intelligence dashboard that publishes a complete report for the previous natural month, preserves verified historical analysis, and fails safely when generation or validation is incomplete.

## Confirmed Product Requirements

- Publish on the first day of each month after the previous month has ended in both China and the United States.
- Use the complete previous natural month as the reporting window.
- Keep the current and future public experience in English.
- Retain historical Chinese files at their existing URLs for backward compatibility, but remove them from public navigation.
- Keep Makeup and Fragrance coverage split by CN/US and Luxury/Masstige.
- Prefer broad, useful coverage over overly aggressive deletion while never inventing products, prices, sizes, sources, or signals.
- Show `Price and size not publicly disclosed` when a verified launch lacks public commercial details.
- Explain Heat Score using the agreed weights: Sales Momentum 40%, Buzz Momentum 30%, Review/Rating 20%, and Trend Fit 10%.
- Preserve evidence grades and clearly label observations that still require official confirmation.
- Keep historical analytical content unchanged; navigation-shell repairs are permitted.

## Root Causes

### Monthly generation

The October 1 run collected 713 source articles successfully, then failed during generation because every heat panel was empty after evidence canonicalization. The generator asks one model call to discover many products from a small, noisy article sample, then applies stricter product and URL evidence rules than the discovery input can satisfy. The result is a structurally valid draft whose candidates are later quarantined.

### Publishing reliability

The LaunchAgent runs in the same checkout used for manual work. Uncommitted files can block pull, rebase, commit, or rollback even when content generation succeeds. It also runs with the system Python rather than a project-owned environment, and a once-only calendar trigger provides no recovery after a transient failure.

### Archive navigation

Past Issues menus are copied into individual HTML snapshots. Relative paths differ by directory depth, several snapshots contain partial or unsorted issue lists, and existing tests inspect only the two current root pages. This allowed broken nested paths, missing files, and inconsistent language links to reach production.

### Observability and documentation

Codex-authenticated generation currently logs the API fallback model name, making successful runs appear to use `gpt-4o-mini`. README and setup documentation still describe the older weekly/API workflow. One test also derives its fixture month from the wall clock, so it fails when the current report has not yet been published.

## Architecture

### 1. Deterministic issue registry

Create one machine-readable issue registry containing the current monthly issue and all legacy weekly snapshots. Navigation rendering reads this registry, sorts entries by explicit publication order, and computes relative links from each page location. Current pages and repaired archive shells therefore share one source of truth without changing historical analytical content.

The registry exposes only English pages. Existing Chinese files remain deployable and reachable by old direct URLs, but no generated English navigation links to them.

### 2. Evidence-first content pipeline

Separate monthly generation into four bounded stages:

1. Collect all configured RSS and focused web sources for the reporting window.
2. Build market/tier candidate pools from the full relevant corpus and retain the exact source URL and source excerpt for every candidate.
3. Ask authenticated Codex to enrich only evidence-backed candidates with positioning, signals, pricing status, trend analysis, and weighted Heat Score inputs.
4. Canonicalize, deduplicate, grade evidence, validate coverage, and render.

Calls are partitioned by category and panel so one weak panel can be retried without regenerating the whole report. Evidence rules remain strict for factual claims but treat missing price or size as an explicit disclosure state rather than grounds for removal. Thin discovery/radar sections can publish with a visible coverage note; core heat panels remain fail-closed.

### 3. Isolated local publisher

Keep the authenticated Codex CLI as the only generation transport. Pin the project run to `gpt-5.6-sol` with a project-defined reasoning effort rather than changing the user's global Codex settings.

Install the scheduler against a dedicated clean automation checkout and project virtual environment. The first run occurs after the US reporting month has ended; idempotent retries later on day 1 and day 2 exit immediately when that data month is already published. A lock prevents overlapping runs.

Each run writes a status record and retains diagnostic artifacts outside published paths. Published files are replaced only after collection, generation, evidence checks, structural checks, rendering, link validation, and deterministic-render checks all pass. Git commit and push happen last. A failed run leaves the current site untouched.

### 4. CI and deployment ownership

Local Codex owns content generation. GitHub Actions owns validation and GitHub Pages deployment only; it must not silently fall back to API-based generation. Manual workflow dispatch validates and deploys already-generated content.

### 5. Verification

Automated coverage will include:

- registry ordering and English-only public navigation;
- relative-link validation from every current and archived page;
- legacy URL preservation;
- deterministic candidate selection and panel-specific retries;
- missing-price disclosure behavior;
- Heat Score weighting and evidence-grade preservation;
- scheduler timing, locking, idempotency, clean-checkout enforcement, and fail-safe rollback;
- a calendar-independent report fixture;
- a full dry run from captured September source data through rendered October pages without pushing.

Before release, run the complete test suite, project checks, whole-site link scan, deterministic render comparison, local visual checks at desktop and mobile widths, and a no-push automation rehearsal. Production publication remains a separate final step after preview approval.

## Migration and Rollback

The first release adds the issue registry, repairs navigation shells, and moves scheduling to the isolated checkout without deleting historical files. The existing LaunchAgent is replaced only after a successful no-push rehearsal. Its previous plist and the current published pages are backed up before activation.

Every publication is a normal Git commit. Rollback is therefore a revert of the publication commit, while the runner's pre-publication snapshot protects against local partial writes.

## Out of Scope

- Rewriting historical analysis solely to increase old issue counts.
- Publishing Chinese current pages.
- Reintroducing paid API generation.
- Fabricating prices, sizes, launches, or performance signals to meet quotas.
