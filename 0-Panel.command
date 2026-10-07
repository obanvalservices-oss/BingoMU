#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo "========================================"
echo "  JewelBingo Panel"
echo "  $(pwd)"
echo "========================================"
if [[ ! -d .venv ]]; then
  echo "Falta .venv — corre 1-Instalar.command"
  read -r -p "Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
export TK_SILENCE_DEPRECATION=1
xattr -cr . >/dev/null 2>&1 || true

echo "Actualizando..."
git fetch origin
git reset --hard origin/main
echo "Commit: $(git rev-parse --short HEAD)"
VER=$(python -c "import panel; print(panel.PANEL_VERSION)")
echo "Version: $VER"
echo "Abriendo..."
python panel.py
echo ""
[[ -f panel_build.log ]] && echo "--- panel_build.log ---" && cat panel_build.log
[[ -f panel_error.log ]] && echo "--- panel_error.log ---" && cat panel_error.log
read -r -p "Enter..."
