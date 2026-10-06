"""
Refresh jewel templates from current screen using saved calibration
(without full recalibration).

  python tools/capture_jewel_templates.py --delay 8
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import ScreenCapture
from src.types import Calibration
from src.vision.templates import JewelClassifier, save_jewel_templates_from_frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cal", type=Path, default=ROOT / "assets" / "calibration" / "default.json")
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "templates")
    ap.add_argument("--delay", type=float, default=8.0)
    args = ap.parse_args()

    if not args.cal.exists():
        print(f"No calibration: {args.cal}")
        print("Run calibrate_wizard.py first.")
        return 1

    cal = Calibration.load(str(args.cal))
    if not cal.jewel_btns:
        print("Calibration has no jewel_btns — recalibrate.")
        return 1

    print("Pon Remote Desktop al frente (Jewel Bingo visible, panel de joyas a la vista).")
    remaining = int(args.delay)
    while remaining > 0:
        print(f"  {remaining}...")
        time.sleep(1)
        remaining -= 1

    cap = ScreenCapture()
    frame = cap.grab()
    cap.close()

    print("Capturando plantillas...")
    saved = save_jewel_templates_from_frame(frame, cal, args.out)
    if len(saved) < 6:
        print(f"WARNING: only saved {saved}")
        return 1

    clf = JewelClassifier(template_dir=str(args.out))
    print(f"OK — {len(clf.templates)} templates listos en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
