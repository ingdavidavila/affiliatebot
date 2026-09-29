#!/bin/bash
# One-time setup on your Mac. Run from the project folder:  ./scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 not found. Install it from https://www.python.org/downloads/ (or: brew install python) and run this again."
  exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Python 3.9 or newer is needed (you have $("$PY" --version)). Install a newer one from python.org."
  exit 1
fi

echo "==> Creating virtual environment in .venv"
"$PY" -m venv .venv
./.venv/bin/python -m pip install --upgrade pip >/dev/null
echo "==> Installing requirements"
./.venv/bin/python -m pip install -r requirements.txt

[ -f config.yaml ] || { cp config.example.yaml config.yaml; echo "==> Created config.yaml"; }
[ -f .env ] || { cp .env.example .env; echo "==> Created .env (add your API keys here later)"; }
mkdir -p data/logs
chmod +x "Start Dashboard.command" scripts/*.sh

echo "==> Building demo data so you can preview the dashboard"
./.venv/bin/python -m bot demo

case "$PWD" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo
    echo "NOTE: this folder is inside Desktop/Documents/Downloads. macOS blocks background"
    echo "      jobs from those folders, so the scheduler won't be able to run the bot."
    echo "      Move the folder to e.g. ~/affiliate-bot before running install_scheduler.sh."
    ;;
esac

echo
echo "Done. Next steps:"
echo "  1. Preview:        double-click 'Start Dashboard.command' (or ./.venv/bin/python -m bot dashboard --demo)"
echo "  2. Test run:       ./.venv/bin/python -m bot run      (dry run, uses fake demo deals)"
echo "  3. Add API keys:   open .env in a text editor"
echo "  4. Automate:       ./scripts/install_scheduler.sh 30  (runs the bot every 30 minutes)"
