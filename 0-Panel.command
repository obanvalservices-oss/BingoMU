#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Run 1-Instalar.command first."
  read -r -p "Press Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
export TK_SILENCE_DEPRECATION=1
xattr -cr . >/dev/null 2>&1 || true

echo "Starting JewelBingo Panel..."
python panel.py
code=$?
if [[ $code -ne 0 ]]; then
  echo ""
  echo "Panel exited with error $code"
  if [[ -f panel_error.log ]]; then
    echo "----- panel_error.log -----"
    cat panel_error.log
  fi
fi
echo ""
read -r -p "Press Enter to close..."
