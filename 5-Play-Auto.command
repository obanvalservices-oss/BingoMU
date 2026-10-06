#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Run 1-Instalar.command first."
  read -r -p "Press Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "AUTO mode — uses in-game Auto-Place."
echo "F8 = stop | mouse to corner = failsafe"
echo ""
read -r -p "Press Enter to start (Ctrl+C cancels)..."
python main.py --mode auto --max-games 10
echo ""
read -r -p "Press Enter to close..."
