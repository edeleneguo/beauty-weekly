#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT=$(cd "$(dirname "$0")/.." && pwd)
AUTOMATION_ROOT="${BEAUTY_WEEKLY_AUTOMATION_ROOT:-$HOME/.openclaw/automation/beauty-weekly}"
PYTHON_BIN="${BEAUTY_WEEKLY_PYTHON:-/opt/homebrew/bin/python3}"
REMOTE_URL=$(git -C "$SOURCE_ROOT" remote get-url origin)

mkdir -p "$(dirname "$AUTOMATION_ROOT")"
if [[ ! -d "$AUTOMATION_ROOT/.git" ]]; then
  git clone --branch main --single-branch "$REMOTE_URL" "$AUTOMATION_ROOT"
fi

if [[ -n "$(git -C "$AUTOMATION_ROOT" status --porcelain --untracked-files=all)" ]]; then
  echo "FAIL: dedicated automation checkout is dirty: $AUTOMATION_ROOT" >&2
  exit 1
fi

git -C "$AUTOMATION_ROOT" fetch origin main
git -C "$AUTOMATION_ROOT" checkout main
git -C "$AUTOMATION_ROOT" merge --ff-only origin/main

if [[ ! -x "$AUTOMATION_ROOT/.venv/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$AUTOMATION_ROOT/.venv"
fi
"$AUTOMATION_ROOT/.venv/bin/python" -m pip install --disable-pip-version-check \
  -r "$AUTOMATION_ROOT/requirements-dev.txt"

env -u CODEX_HOME -u OPENAI_API_KEY -u CODEX_API_KEY -u CODEX_ACCESS_TOKEN \
  /opt/homebrew/bin/codex login status >/dev/null

"$AUTOMATION_ROOT/.venv/bin/python" -m pytest -q \
  "$AUTOMATION_ROOT/tests/test_local_runner.py" \
  "$AUTOMATION_ROOT/tests/test_issue_registry.py" \
  "$AUTOMATION_ROOT/tests/test_site_links.py"

mkdir -p "$AUTOMATION_ROOT/.beauty-weekly-state/logs"
printf 'Automation checkout ready: %s\n' "$AUTOMATION_ROOT"
printf 'Python: %s\n' "$AUTOMATION_ROOT/.venv/bin/python"
