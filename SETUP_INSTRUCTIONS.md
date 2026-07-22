# Zero-Input Auto-Deploy Pipeline — Setup Instructions

## Overview
The pipeline automatically:
1. Calculates current ISO week (no manual week input)
2. Collects raw data from public RSS feeds (Elle, Harper's Bazaar, Glossy, Now Smell This, Cosmopolitan)
3. Generates canonical content (trends/news/products) using an LLM API
4. Validates and renders 4 HTML pages
5. Deploys to GitHub Pages
6. Verifies 3-layer consistency (raw → build → CDN)

## Required GitHub Actions Secrets

Go to: Settings → Secrets and variables → Actions → New repository secret

| Secret Name | Description | Required |
|-------------|-------------|----------|
| `LLM_API_KEY` | API key for LLM provider (OpenAI/Azure/GLM) | YES |
| `LLM_BASE_URL` | Base URL for LLM API (default: https://api.openai.com/v1) | Optional |
| `LLM_MODEL` | Model name (default: gpt-4o-mini) | Optional |

## Workflow File Upload

The current GitHub token lacks the `workflow` scope, so `.github/workflows/weekly-deploy.yml`
must be uploaded manually:

1. Go to: https://github.com/edeleneguo/beauty-weekly/tree/main/.github/workflows
2. Click "Add file" → "Create new file"
3. Name: `weekly-deploy.yml`
4. Copy content from the local file: `.github/workflows/weekly-deploy.yml`
5. Commit with message: "Add weekly-deploy workflow"

## Or: Create New Token with Workflow Scope

1. Go to: https://github.com/settings/tokens
2. Generate new token (classic)
3. Scopes: `repo`, `workflow`
4. Use this token for deployment

## Data Sources (All Public, No API Key Required)
- Elle Beauty RSS: https://www.elle.com/rss/beauty
- Harper's Bazaar Beauty RSS: https://www.harpersbazaar.com/rss/beauty
- Glossy RSS: https://www.glossy.co/feed
- Now Smell This RSS: https://www.nstperfume.com/feed/
- Cosmopolitan Beauty RSS: https://www.cosmopolitan.com/rss/beauty

## Pipeline Scripts (Already in Repo)
- `build/collect.py` — Auto-collects raw data from RSS feeds
- `build/generate_weekly.py` — Generates canonical JSON using LLM API
- `build/deploy_pages.py` — Deploys to GitHub Pages + 3-layer verification
- `build/weekly_update.sh` — Existing validate + render pipeline
- `.github/workflows/weekly-deploy.yml` — GitHub Actions workflow (needs manual upload)

## Triggering the Workflow
After setup, trigger via:
- Automatic: Every Monday 09:00 UTC+8
- Manual: GitHub Actions → "Weekly Beauty Report — Zero-Input Auto-Deploy" → Run workflow
