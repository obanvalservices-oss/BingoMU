#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "JewelBingo Panel — $(pwd)"
if [[ ! -d .venv ]]; then
  echo "Falta .venv"
  read -r -p "Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
export TK_SILENCE_DEPRECATION=1
xattr -cr . >/dev/null 2>&1 || true
git fetch origin
git reset --hard origin/main
echo "Commit: $(git rev-parse --short HEAD)"
python -c "import panel; print('Version:', panel.PANEL_VERSION)"
python panel.py
echo ""
[[ -f panel_error.log ]] && echo "=== panel_error.log ===" && cat panel_error.log
read -r -p "Enter..."
