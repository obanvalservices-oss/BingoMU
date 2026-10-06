"""
Extract jewel color samples / optional template crops from a video frame.

  python tools/extract_templates.py --ms 35000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import VideoCapture, crop
from src.types import Calibration
from src.vision.board import BoardReader, cell_rects
from src.vision.templates import JewelClassifier, dominant_jewel_score, DEFAULT_PROFILES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, default=ROOT / "VID_20261006_094447.mp4")
    ap.add_argument("--cal", type=Path, default=ROOT / "assets" / "calibration" / "default.json")
    ap.add_argument("--ms", type=float, default=35000.0)
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "templates")
    args = ap.parse_args()

    if not args.cal.exists():
        print("Run tools/calibrate.py or tools/replay_video.py --save-cal-estimate first.")
        return 1

    cal = Calibration.load(str(args.cal))
    vc = VideoCapture(args.video)
    frame = vc.seek_ms(args.ms)
    vc.close()
    if frame is None:
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    reader = BoardReader(cal, JewelClassifier())
    board = reader.read(frame)
    cells = cell_rects(cal.grid)

    # Save each non-FREE cell as candidate template named by classification
    counts: dict[str, int] = {}
    for r in range(5):
        for c in range(5):
            label = board.cells[r][c]
            if not label or label == "FREE":
                continue
            patch = crop(frame, cells[r][c])
            n = counts.get(label, 0)
            counts[label] = n + 1
            path = args.out / f"{label}_{n}.png"
            cv2.imwrite(str(path), patch)
            # Also keep canonical first sample as label.png
            if n == 0:
                cv2.imwrite(str(args.out / f"{label}.png"), patch)

    profile_path = ROOT / "assets" / "calibration" / "color_profiles.json"
    with profile_path.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_PROFILES, f, indent=2)

    print("Board read:")
    for row in board.cells:
        print(row)
    print(f"Templates written to {args.out}")
    print(f"Profiles -> {profile_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
