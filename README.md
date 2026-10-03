# Beauty Weekly Monthly Intelligence Dashboard

Beauty Weekly publishes English Makeup and Fragrance market intelligence for the previous natural month. The trusted Mac generates the report with the ChatGPT-authenticated Codex CLI; GitHub validates and serves only committed artifacts.

## Production Pages

- `index.html`: Makeup
- `fragrance.html`: Fragrance
- `archive/`: immutable historical analysis with a repairable navigation shell
- `data/issues.json`: single ordered registry for public Past Issues navigation
- `data/months/YYYY-MM/`: collected sources and canonical monthly bundle

Historical Chinese URLs are retained for compatibility but are not linked from the public navigation.

## Monthly Data Flow

```text
RSS and focused public-source collection
  -> full category evidence pool
  -> stable source IDs and market/tier candidates
  -> authenticated Codex enrichment
  -> evidence grading and coverage gates
  -> deterministic English render
  -> navigation and whole-site link checks
  -> atomic Git commit and push
  -> GitHub CI and Pages deployment
```

The generator uses `gpt-5.6-sol` through the local Codex login, not an API key. A product can enter a formal panel only when its source ID resolves to collected evidence and the evidence names the product. Missing price or size is represented as `Price and size not publicly disclosed`; it is not fabricated and does not automatically remove a verified launch.

Heat Score uses the agreed interpretation:

- Sales Momentum: 40%
- Buzz Momentum: 30%
- Review/Rating: 20%
- Trend Fit: 10%

## Local Verification

Create a Python environment and install the pinned validation dependencies:

```bash
/opt/homebrew/bin/python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
BEAUTY_MONTHLY_MONTH=2026-09 .venv/bin/python build/monthly_local_runner.py \
  --month 2026-09 --skip-collect --no-commit
```

The complete fail-closed quality gate is:

```bash
BEAUTY_MONTHLY_MONTH=2026-09 ./build/check.sh
```

It checks secrets, lint, tests, canonical data, evidence, scoring, deterministic rendering, navigation drift, and every local HTML link.

## Automation

See `docs/local-codex-automation.md`. The scheduler runs only from a dedicated clean checkout under `~/.openclaw/automation/beauty-weekly`; ordinary development or Jennie workspaces are never used for automatic publication.

GitHub workflows do not collect data, call a model, or mutate the repository. CI validates committed content, and the manual deploy workflow publishes a validated commit to GitHub Pages.
