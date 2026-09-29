#!/bin/bash
# Double-click in Finder to open the dashboard. Close this Terminal window to stop it.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First-time setup..."
  ./scripts/setup_mac.sh || { read -r -p "Setup failed. Press Enter to close."; exit 1; }
fi
# Shows demo data until the bot has made its first real run.
if [ -f data/affiliate.db ]; then
  ./.venv/bin/python -m bot dashboard
else
  echo "No real data yet, opening the demo. Run the bot once to switch to your own numbers."
  ./.venv/bin/python -m bot dashboard --demo
fi
