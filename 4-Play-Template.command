#!/bin/bash
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Run 1-Instalar.command first."
  read -r -p "Press Enter..."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "TEMPLATE mode — ChatGPT pattern (recommended)."
echo "F8 = stop | mouse to corner = failsafe"
echo ""
echo "Tras Enter: 5s de cuenta regresiva para poner Remote Desktop al frente."
echo ""
read -r -p "Press Enter to start (Ctrl+C cancels)..."
python main.py --mode template --max-games 10 --countdown 5
echo ""
read -r -p "Press Enter to close..."
