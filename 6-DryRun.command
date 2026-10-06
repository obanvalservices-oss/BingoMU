#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Run 1-Instalar.command first."
  read -r -p "Press Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Dry-run: logs decisions, minimal mouse movement."
echo "F8 = stop. Remote Desktop should be visible."
echo ""
python main.py --mode template --dry-run --max-games 1
echo ""
read -r -p "Press Enter to close..."
