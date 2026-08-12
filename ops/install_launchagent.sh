#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE="$ROOT/ops/com.edelene.beauty-weekly-monthly.plist"
TARGET="$HOME/Library/LaunchAgents/com.edelene.beauty-weekly-monthly.plist"
mkdir -p "$ROOT/.beauty-weekly-state/logs" "$HOME/Library/LaunchAgents"
plutil -lint "$SOURCE"
cp "$SOURCE" "$TARGET"
launchctl bootout "gui/$(id -u)" "$TARGET" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
launchctl print "gui/$(id -u)/com.edelene.beauty-weekly-monthly"
