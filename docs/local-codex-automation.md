# Local Codex Monthly Automation

## Ownership

The trusted Mac is the only content-generation owner. It uses the default ChatGPT-authenticated `~/.codex` session and pins the project run to `gpt-5.6-sol` with high reasoning. No OpenAI API key is required or inherited.

GitHub Actions validates and deploys committed files only. It cannot silently switch to an API model or generate a replacement report.

## Schedule

The LaunchAgent starts at these Asia/Shanghai wall-clock times:

- Day 1, 18:00: primary run, after the previous US calendar month has ended
- Day 1, 22:00: recovery run
- Day 2, 09:00: final recovery run

The runner reads `deploy-manifest.json` and exits successfully when the previous month is already published, so recovery invocations are harmless.

## Install

The installer creates or updates a dedicated clean checkout, builds its `.venv`, verifies the Codex login and focused tests, backs up the previous plist, and then loads the LaunchAgent:

```bash
bash ops/install_launchagent.sh
```

The automation checkout is:

```text
~/.openclaw/automation/beauty-weekly
```

Automatic publication refuses to start if that checkout contains unexpected changes. A manually copied `raw_collected.json` is allowed only with `--skip-collect`.

## Manual Rehearsal

Run from a clean checkout with a project virtual environment:

```bash
CODEX_MODEL=gpt-5.6-sol CODEX_REASONING_EFFORT=high \
  .venv/bin/python build/monthly_local_runner.py \
  --month 2026-09 --skip-collect --no-commit
```

`--no-commit` performs collection reuse, generation, validation, rendering, and manifest creation without committing or pushing.

## Failure Safety

- `flock` prevents overlapping runs.
- Public files are snapshotted before work begins.
- Any generation or validation failure restores the prior public pages.
- Canonical failure artifacts remain available for diagnosis but are not published.
- Git commit and push occur only after every quality gate passes.
- `.beauty-weekly-state/monthly-status.json` records `running`, `failed`, `validated`, or `published` with a UTC timestamp.

Inspect status and logs:

```bash
launchctl print gui/$(id -u)/com.edelene.beauty-weekly-monthly
cat ~/.openclaw/automation/beauty-weekly/.beauty-weekly-state/monthly-status.json
tail -n 200 ~/.openclaw/automation/beauty-weekly/.beauty-weekly-state/logs/monthly.err.log
```

## Rollback

The previous LaunchAgent plist is retained beside the installed plist with a timestamped `.backup-*` suffix. Every successful publication is a normal Git commit, so production rollback is a standard revert followed by validation and Pages deployment.
