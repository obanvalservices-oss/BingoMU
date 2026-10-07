#!/bin/bash
# Launch JewelBingo panel WITHOUT tying RAM to Terminal scrollback.
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

# Detach GUI from this Terminal so scrollback cannot grow to tens of GB.
# Logs (errors only) go to logs/panel_launch.log — close this window after panel opens.
nohup python panel.py >>logs/panel_launch.log 2>&1 &
PID=$!
sleep 1
if kill -0 "$PID" 2>/dev/null; then
  echo ""
  echo "Panel abierto (PID $PID)."
  echo "Puedes CERRAR esta Terminal — el panel sigue corriendo."
  echo "Errores: logs/panel_launch.log"
else
  echo "Falló al abrir el panel. Ver logs/panel_launch.log"
  tail -n 40 logs/panel_launch.log 2>/dev/null
fi
echo ""
read -r -p "Enter para cerrar esta ventana..."
