# Beauty Weekly Monthly Pipeline Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore reliable English-only public navigation, evidence-rich monthly generation, and fail-safe local Codex publication for Beauty Weekly.

**Architecture:** A versioned issue registry becomes the only navigation source, while a focused evidence-pool layer feeds panel-specific Codex generation. A dedicated clean checkout and project Python environment run an idempotent, locked publication pipeline; GitHub Actions only validates and deploys committed output.

**Tech Stack:** Python 3.12, pytest, BeautifulSoup, Pydantic, static HTML, GitHub Actions, macOS LaunchAgent, authenticated Codex CLI.

---

### Task 1: Establish a clean baseline and regression inventory

**Files:**
- Modify: `tests/test_month.py`
- Create: `tests/test_site_links.py`
- Create: `build/check_site_links.py`

- [ ] **Step 1: Run the focused baseline and capture the existing failures**

Run:

```bash
pytest -q tests/test_local_runner.py tests/test_past_issues_selector.py tests/test_workflow_structure.py tests/test_month.py
```

Expected: the wall-clock-dependent September fixture test fails; existing selector tests pass despite known broken archive links.

- [ ] **Step 2: Write a failing whole-site link regression test**

Create a test that walks root and `archive/**/*.html`, parses local `href` and `<option value>` references, resolves each path relative to its containing page, and reports every missing target. Ignore fragments, `http(s)`, `mailto`, and JavaScript URLs.

- [ ] **Step 3: Verify the test exposes the archive defects**

Run:

```bash
pytest -q tests/test_site_links.py
```

Expected: FAIL with the known Week 30 nested `archive/week-30/archive/...` paths, missing current Chinese roots, and malformed archive references.

- [ ] **Step 4: Make the month test independent of the current date**

Point `test_radar_products_have_trend_fields` at the latest complete committed fixture discovered from `data/months/*/report.json`, rather than computing the previous month from today's date.

- [ ] **Step 5: Re-run the fixed calendar test**

Run:

```bash
pytest -q tests/test_month.py::TestNewLaunchTrendExpansion::test_radar_products_have_trend_fields
```

Expected: PASS against a committed complete fixture.

- [ ] **Step 6: Commit the baseline tests**

```bash
git add tests/test_month.py tests/test_site_links.py build/check_site_links.py
git commit -m "test: cover monthly fixtures and site links"
```

### Task 2: Introduce the deterministic issue registry

**Files:**
- Create: `data/issues.json`
- Create: `beauty_weekly/issues.py`
- Create: `build/update_issue_navigation.py`
- Create: `tests/test_issue_registry.py`
- Modify: `tests/test_past_issues_selector.py`

- [ ] **Step 1: Write failing registry-order and navigation tests**

The tests must require:

```python
assert [issue["id"] for issue in load_issues()] == [
    "2026-W30", "2026-W29", "2026-W28", "2026-W27",
    "2026-W26", "2026-W25", "2026-W23",
]
assert all(issue["language"] == "en" for issue in public_issues())
```

They must also assert that relative links generated for a root page and `archive/week-30/index.html` resolve to the same targets.

- [ ] **Step 2: Verify the registry API does not exist yet**

Run:

```bash
pytest -q tests/test_issue_registry.py
```

Expected: FAIL because `beauty_weekly.issues` and `data/issues.json` do not exist.

- [ ] **Step 3: Implement the registry loader and relative-link builder**

Expose focused functions:

```python
def load_issues(path: Path = DEFAULT_REGISTRY) -> list[dict]: ...
def public_issues(path: Path = DEFAULT_REGISTRY) -> list[dict]: ...
def relative_issue_url(page: Path, target: Path) -> str: ...
def render_issue_options(page: Path, category: str) -> str: ...
```

Validate unique IDs, strict descending order, existing English category targets, and no public Chinese entries.

- [ ] **Step 4: Add a navigation-shell updater**

`build/update_issue_navigation.py` replaces only the Past Issues `<select>` and category link in existing HTML. It must preserve all analytical sections byte-for-byte outside the banner fragment and support `--check` for CI.

- [ ] **Step 5: Verify registry behavior**

Run:

```bash
pytest -q tests/test_issue_registry.py tests/test_past_issues_selector.py
```

Expected: PASS.

- [ ] **Step 6: Commit the registry**

```bash
git add data/issues.json beauty_weekly/issues.py build/update_issue_navigation.py tests/test_issue_registry.py tests/test_past_issues_selector.py
git commit -m "feat: centralize past issue navigation"
```

### Task 3: Repair all public navigation without changing historical analysis

**Files:**
- Modify: `index.html`
- Modify: `fragrance.html`
- Modify: `archive/week-*/index.html`
- Modify: `archive/week-*/fragrance.html`
- Modify: `build/monthly_update.sh`
- Modify: `build/check.sh`

- [ ] **Step 1: Run the navigation updater in write mode**

Run:

```bash
python build/update_issue_navigation.py
```

Expected: current and English archive pages receive the same complete descending issue list with depth-correct links and no Chinese navigation.

- [ ] **Step 2: Confirm changes are limited to the navigation shell**

Run a script that strips the banner fragment before comparing pre-change and post-change archive bodies. Expected: no analytical-content differences.

- [ ] **Step 3: Add navigation and link checks to the quality gate**

Append these fail-closed commands to `build/check.sh` and the monthly render sequence:

```bash
python3 build/update_issue_navigation.py --check
python3 build/check_site_links.py
```

- [ ] **Step 4: Verify every local target**

Run:

```bash
pytest -q tests/test_issue_registry.py tests/test_past_issues_selector.py tests/test_site_links.py
python build/check_site_links.py
```

Expected: PASS with zero broken local links.

- [ ] **Step 5: Commit the navigation repair**

```bash
git add index.html fragrance.html archive build/monthly_update.sh build/check.sh
git commit -m "fix: repair and normalize issue navigation"
```

### Task 4: Build evidence pools before model enrichment

**Files:**
- Create: `beauty_weekly/candidates.py`
- Create: `tests/test_candidate_pools.py`
- Modify: `build/generate_monthly.py`

- [ ] **Step 1: Write failing candidate-pool tests**

Tests must prove that the pool:

- considers the complete relevant corpus rather than a 30-article prompt slice;
- keeps exact article URLs and excerpts;
- rejects cross-category noise;
- partitions candidates by CN/US and Luxury/Masstige;
- deduplicates the same product across syndicated articles while retaining multiple evidence records;
- ranks direct brand and reputable editorial evidence above aggregators.

- [ ] **Step 2: Verify the tests fail for the current prompt-only selector**

Run:

```bash
pytest -q tests/test_candidate_pools.py
```

Expected: FAIL because no evidence-pool API exists.

- [ ] **Step 3: Implement deterministic evidence pools**

Expose:

```python
def build_candidate_pools(
    articles: list[dict], category: str, month: str
) -> dict[str, list[CandidateEvidence]]: ...
```

Each `CandidateEvidence` contains normalized product name, market, tier hint, evidence URL, title, excerpt, source type, publication date, and relevance score. The implementation must reuse existing category relevance and evidence classification rules rather than duplicate policy.

- [ ] **Step 4: Replace the shared 30-article prompt input**

Generate panel prompts from the relevant evidence pool. A prompt may cap its own token window, but the pool construction and candidate ranking must inspect the full corpus. Include stable candidate IDs so model output refers to evidence rather than inventing URLs.

- [ ] **Step 5: Verify deterministic selection**

Run:

```bash
pytest -q tests/test_candidate_pools.py tests/test_monthly_evidence_thresholds.py tests/test_reference_sources.py
```

Expected: PASS.

- [ ] **Step 6: Commit candidate discovery**

```bash
git add beauty_weekly/candidates.py build/generate_monthly.py tests/test_candidate_pools.py
git commit -m "feat: build evidence-backed monthly candidates"
```

### Task 5: Generate and retry one panel at a time

**Files:**
- Modify: `build/generate_monthly.py`
- Create: `tests/test_panel_generation.py`
- Modify: `tests/test_llm_transport.py`

- [ ] **Step 1: Write failing panel-generation tests**

Use a deterministic fake transport to assert:

- four heat panels and four radar panels are requested independently;
- output may reference only supplied candidate IDs;
- only a deficient panel is retried;
- a radar panel can publish below its soft target with a coverage note;
- a heat panel below its hard minimum aborts publication;
- `Price and size not publicly disclosed` is emitted when verified evidence lacks those values.

- [ ] **Step 2: Verify current category-wide generation fails the tests**

Run:

```bash
pytest -q tests/test_panel_generation.py
```

Expected: FAIL because the current generator regenerates a whole category and accepts free-form product URLs.

- [ ] **Step 3: Add a transport seam and panel generator**

Implement focused functions:

```python
def generate_panel(panel: PanelRequest, call: Callable[[str, str, int], str]) -> list[dict]: ...
def retry_deficient_panels(result: dict, pools: dict, call: Callable, attempts: int = 3) -> dict: ...
```

Validate candidate IDs before product construction. Preserve existing A/B formal routing and C observation routing.

- [ ] **Step 4: Pin and accurately report the Codex model**

Under Codex transport, log `CODEX_MODEL` or the explicit project default `gpt-5.6-sol`; never log the API fallback `MODEL`. Pass the project reasoning effort using Codex CLI configuration without changing `~/.codex/config.toml`.

- [ ] **Step 5: Verify panel behavior and transport observability**

Run:

```bash
pytest -q tests/test_panel_generation.py tests/test_llm_transport.py tests/test_monthly_evidence_thresholds.py tests/test_radar_trend_validation.py
```

Expected: PASS.

- [ ] **Step 6: Commit panel generation**

```bash
git add build/generate_monthly.py tests/test_panel_generation.py tests/test_llm_transport.py
git commit -m "fix: generate monthly products by evidence panel"
```

### Task 6: Harden the local publisher and scheduler

**Files:**
- Modify: `build/monthly_local_runner.py`
- Modify: `tests/test_local_runner.py`
- Modify: `ops/com.edelene.beauty-weekly-monthly.plist`
- Modify: `ops/install_launchagent.sh`
- Create: `ops/prepare_automation_checkout.sh`

- [ ] **Step 1: Write failing runner tests**

Tests must require:

- refusal to publish from a dirty automation checkout;
- an idempotent successful exit when the requested month is already in `deploy-manifest.json`;
- a JSON status record for running, failed, and published states;
- restoration of public files after any pre-push failure;
- use of project Python and explicit `CODEX_MODEL=gpt-5.6-sol`;
- non-overlapping lock behavior.

- [ ] **Step 2: Verify the current runner fails the new requirements**

Run:

```bash
pytest -q tests/test_local_runner.py
```

Expected: FAIL on dirty-checkout, idempotency, status, and explicit-model assertions.

- [ ] **Step 3: Implement clean-checkout and state guarantees**

Add `ensure_clean_checkout()`, `already_published(month)`, and `write_status(...)`. Keep generated diagnostics outside tracked public paths until validation succeeds. Preserve the existing snapshot/restore behavior and stage only the exact month and published artifacts.

- [ ] **Step 4: Prepare a dedicated automation checkout**

`ops/prepare_automation_checkout.sh` creates or fast-forwards a dedicated clone/worktree, builds `.venv`, installs locked requirements, verifies Codex login, performs a no-push preflight, and prints the exact LaunchAgent path. It must never reuse a dirty development checkout.

- [ ] **Step 5: Update the LaunchAgent schedule**

Use explicit calendar entries after the US month has closed, plus recovery attempts later on day 1 and day 2. Every entry calls the dedicated checkout's `.venv/bin/python`. Idempotency makes repeat invocations harmless.

- [ ] **Step 6: Verify runner and plist behavior**

Run:

```bash
pytest -q tests/test_local_runner.py
plutil -lint ops/com.edelene.beauty-weekly-monthly.plist
```

Expected: PASS and valid plist.

- [ ] **Step 7: Commit publisher hardening**

```bash
git add build/monthly_local_runner.py tests/test_local_runner.py ops
git commit -m "fix: isolate and harden monthly publishing"
```

### Task 7: Make GitHub validation-only and refresh operating docs

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/weekly-deploy.yml`
- Modify: `tests/test_workflow_structure.py`
- Modify: `README.md`
- Modify: `docs/local-codex-automation.md`
- Modify: `SETUP_INSTRUCTIONS.md`

- [ ] **Step 1: Write failing workflow ownership tests**

Require that no GitHub job invokes monthly generation or references `LLM_API_KEY`, `LLM_BASE_URL`, or `LLM_MODEL`. Require CI to run the registry and whole-site link checks.

- [ ] **Step 2: Verify the old recovery workflow fails the tests**

Run:

```bash
pytest -q tests/test_workflow_structure.py
```

Expected: FAIL because the workflow still contains API generation and commit/push stages.

- [ ] **Step 3: Reduce GitHub workflows to validate and deploy**

Keep pull-request/push validation and manual deployment of committed artifacts. Remove API generation, repository mutation, and stale schedule conditions.

- [ ] **Step 4: Replace stale weekly/API documentation**

Document the monthly data flow, English-only public pages, issue registry, local Codex Auth ownership, dedicated checkout, schedule/retry behavior, logs/status, dry-run command, and rollback procedure. Mark the old setup instructions as retired or replace them entirely.

- [ ] **Step 5: Verify workflow and documentation checks**

Run:

```bash
pytest -q tests/test_workflow_structure.py
python build/check_secrets.py
```

Expected: PASS.

- [ ] **Step 6: Commit CI and docs**

```bash
git add .github tests/test_workflow_structure.py README.md docs/local-codex-automation.md SETUP_INSTRUCTIONS.md
git commit -m "docs: clarify monthly automation ownership"
```

### Task 8: Rehearse September generation and produce the preview

**Files:**
- Create: `data/months/2026-09/report.json`
- Create: `data/months/2026-09/sources.json`
- Create: `data/months/2026-09/scoring.json`
- Create: `data/months/2026-09/manifest.json`
- Modify: `index.html`
- Modify: `fragrance.html`
- Modify: `deploy-manifest.json`
- Modify: `.deploy-manifest-hash`

- [ ] **Step 1: Copy the already-collected September raw corpus into the isolated worktree**

Copy only `data/months/2026-09/raw_collected.json` from the preserved development checkout and record its SHA256 before and after. Do not copy unrelated dirty files.

- [ ] **Step 2: Run the authenticated no-push monthly rehearsal**

Run:

```bash
CODEX_MODEL=gpt-5.6-sol CODEX_REASONING_EFFORT=high \
  .venv/bin/python build/monthly_local_runner.py \
  --month 2026-09 --skip-collect --no-commit
```

Expected: all four canonical files and both English root pages are generated; no Git commit or push occurs.

- [ ] **Step 3: Run complete verification**

Run:

```bash
pytest -q
ruff check .
./build/check.sh
python build/check_site_links.py
git diff --check
```

Expected: all commands pass with no warnings treated as errors.

- [ ] **Step 4: Verify visual behavior**

Serve the worktree locally and inspect Makeup and Fragrance at desktop and mobile widths. Confirm no overlap, all Past Issues entries are ordered and clickable, no Chinese navigation is visible, and data panels remain readable. Save screenshots under ignored `.preview/`.

- [ ] **Step 5: Commit the verified preview artifacts**

```bash
git add data/months/2026-09 index.html fragrance.html deploy-manifest.json .deploy-manifest-hash
git commit -m "feat: publish verified September monthly data"
```

- [ ] **Step 6: Present the preview before production publication**

Start a local server, provide the preview URL and concise coverage summary, and wait for the user's final release approval. Do not push to `main` or replace the installed LaunchAgent before that approval.
