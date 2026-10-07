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
mkdir -p logs
xattr -cr . >/dev/null 2>&1 || true
git fetch origin
git reset --hard origin/main
echo "Commit: $(git rev-parse --short HEAD)"
python -c "import panel; print('Version:', panel.PANEL_VERSION)"

# Mac-safe detach (nohup often breaks Tk windows)
python launch_panel.py
echo ""
sleep 2
if [[ -f logs/panel_launch.log ]]; then
  echo "--- ultimas lineas del log ---"
  tail -n 20 logs/panel_launch.log
fi
echo ""
read -r -p "Enter para cerrar esta ventana..."
