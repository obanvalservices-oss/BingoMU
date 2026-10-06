#!/bin/bash
# Double-click on macOS to install
cd "$(dirname "$0")"
chmod +x install_mac.sh 2-Calibrar.command 3-Simular.command 4-Play-Template.command 5-Play-Auto.command 6-DryRun.command 2>/dev/null || true
exec bash ./install_mac.sh
