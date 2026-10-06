#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Run 1-Instalar.command first."
  read -r -p "Press Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python tools/simulate_offline.py --template --games 20 --sims 400
echo ""
read -r -p "Press Enter to close..."
