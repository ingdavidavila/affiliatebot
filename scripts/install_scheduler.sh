#!/bin/bash
# Runs the bot automatically every N minutes using macOS launchd.
#   ./scripts/install_scheduler.sh        # every 30 minutes
#   ./scripts/install_scheduler.sh 60     # every hour
# The bot only runs while your Mac is awake. Remove with ./scripts/uninstall_scheduler.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="$PWD"
MINUTES="${1:-30}"
LABEL="com.affiliatebot.run"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$PROJECT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Run ./scripts/setup_mac.sh first."
  exit 1
fi
case "$PROJECT" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "This folder is inside Desktop/Documents/Downloads, which macOS blocks for background jobs."
    echo "Move it (e.g. mv \"$PROJECT\" ~/affiliate-bot), run setup again there, then retry."
    exit 1
    ;;
esac

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/data/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>bot</string><string>run</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>StartInterval</key><integer>$((MINUTES * 60))</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$PROJECT/data/logs/scheduler.out.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/data/logs/scheduler.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Scheduler installed: the bot runs every $MINUTES minutes while your Mac is awake."
echo "Logs: data/logs/bot.log   Pause any time from the dashboard."
