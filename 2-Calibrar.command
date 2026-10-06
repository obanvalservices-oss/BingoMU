#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Run 1-Instalar.command first."
  read -r -p "Press Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo ""
echo "IMPORTANTE:"
echo "  Despues de Enter tendras 8 segundos para poner"
echo "  Chrome Remote Desktop al FRENTE (Jewel Bingo visible)"
echo "  y sacar esta Terminal del medio."
echo ""
echo "Al marcar puntos: + / - / rueda = zoom para mas precision."
echo ""
read -r -p "Enter para empezar la cuenta regresiva..."
python tools/calibrate_wizard.py --delay 8
echo ""
read -r -p "Press Enter to close..."
