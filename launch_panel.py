"""Start panel.py detached (Mac-safe) so closing Terminal does not kill Tk."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "logs" / "panel_launch.log"


def main() -> int:
    os.chdir(ROOT)
    os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n--- launch {py} panel.py ---\n")
        log.flush()
        proc = subprocess.Popen(
            [py, "-u", str(ROOT / "panel.py")],
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # survive Terminal close; keep Aqua GUI
            env=os.environ.copy(),
        )
    print(f"Panel lanzado PID={proc.pid}")
    print("Ya puedes cerrar el Terminal.")
    print(f"Si no aparece:  cat {LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
