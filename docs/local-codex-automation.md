# Local Codex monthly automation

The trusted Mac is the single scheduler owner. On the first day of each month
at 09:00 Asia/Shanghai it collects the previous month's sources, generates the
canonical bundle with the ChatGPT-authenticated Codex CLI, validates and renders
the site, and pushes only after every gate passes. GitHub Actions then runs CI
and GitHub Pages publishes the committed static files.

The runner strips `CODEX_HOME`, `OPENAI_API_KEY`, `CODEX_API_KEY`, and
`CODEX_ACCESS_TOKEN`, ensuring it uses the default `~/.codex` ChatGPT session.
It never reads, copies, or commits Codex credentials. A lock prevents overlap;
on failure it restores all canonical and published files.

Manual dry run:

```bash
env -u CODEX_HOME /usr/bin/python3 build/monthly_local_runner.py --month 2026-07 --no-commit
```

Install and load the monthly LaunchAgent:

```bash
bash ops/install_launchagent.sh
```

Inspect status and logs:

```bash
launchctl print gui/$(id -u)/com.edelene.beauty-weekly-monthly
tail -n 200 .beauty-weekly-state/logs/monthly.err.log
```
