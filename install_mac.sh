#!/bin/bash
# Jewel Bingo Bot — macOS installer
# Double-click "1-Instalar.command" or run: ./install_mac.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "============================================"
echo "  Jewel Bingo Bot — Install (macOS)"
echo "============================================"
echo "Folder: $ROOT"
echo ""
echo "Runs on THIS Mac (Chrome Remote Desktop)."
echo "Do NOT install on the Windows game PC."
echo ""

if command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "python3 not found."
  if command -v brew >/dev/null 2>&1; then
    echo "Installing Python via Homebrew..."
    brew install python
    PY="$(command -v python3)"
  else
    echo "Install Python 3.11+ from https://www.python.org/downloads/macos/"
    echo "or Homebrew: https://brew.sh"
    read -r -p "Press Enter to exit..."
    exit 1
  fi
fi

echo "Python: $($PY --version)"

if [[ ! -d .venv ]]; then
  echo "Creating .venv ..."
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo ""
echo "============================================"
echo "  Install complete."
echo "============================================"
echo ""
echo "macOS permissions (System Settings → Privacy & Security):"
echo "  • Screen Recording  → Terminal / Python"
echo "  • Accessibility     → Terminal / Python"
echo ""
echo "Next: open Chrome Remote Desktop with Jewel Bingo visible,"
echo "then double-click  2-Calibrar.command"
echo ""
read -r -p "Press Enter to close..."
