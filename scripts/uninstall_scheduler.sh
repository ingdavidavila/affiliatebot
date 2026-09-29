#!/bin/bash
# Stops the automatic runs installed by install_scheduler.sh
LABEL="com.affiliatebot.run"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Scheduler removed. The bot will no longer run on its own."
