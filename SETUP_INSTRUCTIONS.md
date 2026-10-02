# Setup Instructions

The former weekly GitHub/API setup has been retired. Do not configure `LLM_API_KEY`, `LLM_BASE_URL`, or `LLM_MODEL` GitHub secrets for report generation.

Current setup and operating instructions are maintained in:

- `README.md` for architecture and validation
- `docs/local-codex-automation.md` for the authenticated local scheduler, installation, logs, and rollback

Install or refresh the trusted Mac scheduler with:

```bash
bash ops/install_launchagent.sh
```
