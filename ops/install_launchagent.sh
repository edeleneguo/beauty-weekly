#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE="$ROOT/ops/com.edelene.beauty-weekly-monthly.plist"
TARGET="$HOME/Library/LaunchAgents/com.edelene.beauty-weekly-monthly.plist"
bash "$ROOT/ops/prepare_automation_checkout.sh"
mkdir -p "$HOME/.openclaw/automation/beauty-weekly/.beauty-weekly-state/logs" \
  "$HOME/Library/LaunchAgents"
plutil -lint "$SOURCE"
if [[ -f "$TARGET" ]]; then
  cp "$TARGET" "$TARGET.backup-$(date +%Y%m%d-%H%M%S)"
fi
cp "$SOURCE" "$TARGET"
launchctl bootout "gui/$(id -u)" "$TARGET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
launchctl print "gui/$(id -u)/com.edelene.beauty-weekly-monthly"
