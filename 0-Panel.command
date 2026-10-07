#!/bin/bash
# JewelBingo Panel launcher — always syncs to latest main before opening.
cd "$(dirname "$0")" || exit 1

echo "========================================"
echo "  JewelBingo Panel launcher"
echo "  folder: $(pwd)"
echo "========================================"

if [[ ! -d .venv ]]; then
  echo "ERROR: falta .venv — corre 1-Instalar.command primero."
  read -r -p "Enter..."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export TK_SILENCE_DEPRECATION=1
xattr -cr . >/dev/null 2>&1 || true

echo ""
echo "Actualizando desde GitHub..."
git fetch origin
git reset --hard origin/main
echo "Commit actual: $(git rev-parse --short HEAD)"
echo ""

VER=$(python -c "import panel; print(panel.PANEL_VERSION)" 2>/dev/null || echo "UNKNOWN")
echo "Panel version cargada: $VER"
EXPECTED="2026-10-07-v4"
if [[ "$VER" != "$EXPECTED" ]]; then
  echo ""
  echo "ADVERTENCIA: esperaba $EXPECTED, tengo $VER"
  echo "Si la UI es gris sin franja naranja de version, el pull fallo."
  echo ""
fi

echo "Abriendo panel..."
python panel.py
code=$?
echo ""
if [[ $code -ne 0 ]]; then
  echo "Panel salio con error $code"
  [[ -f panel_error.log ]] && cat panel_error.log
fi
read -r -p "Enter para cerrar..."
