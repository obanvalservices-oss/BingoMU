"""Refine calibration ROIs for the reference 1920x1080 recording."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.types import Calibration, Rect
from src.vision.board import BoardReader, cell_rects
from src.vision.templates import JewelClassifier
from src.capture import crop


def main() -> None:
    # Manually tuned from frame_35000 / preview (Jewel Bingo modal inside MU window)
    # Overlay ≈ Jewel Bingo panel (not full MU window)
    overlay = Rect(700, 140, 520, 560)
    # Top 3 treasure boxes — top-left is index 0
    boxes = Rect(780, 175, 200, 70)
    # 5x5 jewel grid
    grid = Rect(760, 255, 300, 300)
    # Auto-Place to the right of top of grid
    auto_btn = Rect(1080, 255, 90, 40)
    # Start Game (lower right of panel / when shown)
    start_btn = Rect(900, 620, 160, 45)
    # Reward OK
    reward_btn = Rect(900, 640, 160, 45)
    # Right-side jewel legend (blink / draw indicator)
    draw_jewel_roi = Rect(1075, 310, 120, 220)
    # Score area (if visible on right panel)
    score_roi = Rect(1075, 530, 120, 50)

    cal = Calibration(
        overlay=overlay,
        grid=grid,
        boxes=boxes,
        auto_btn=auto_btn,
        start_btn=start_btn,
        reward_btn=reward_btn,
        score_roi=score_roi,
        draw_jewel_roi=draw_jewel_roi,
    )
    out = ROOT / "assets" / "calibration" / "default.json"
    cal.save(str(out))

    frame = cv2.imread(str(ROOT / "assets" / "calibration" / "raw_35000.png"))
    if frame is None:
        cap = cv2.VideoCapture(str(ROOT / "VID_20261006_094447.mp4"))
        cap.set(cv2.CAP_PROP_POS_MSEC, 35000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise SystemExit("no frame")

    vis = frame.copy()
    for name, r in [
        ("overlay", overlay),
        ("boxes", boxes),
        ("grid", grid),
        ("auto", auto_btn),
        ("draw", draw_jewel_roi),
        ("score", score_roi),
    ]:
        cv2.rectangle(vis, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 255, 255), 2)
        cv2.putText(vis, name, (r.x, r.y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    reader = BoardReader(cal, JewelClassifier())
    board = reader.read(frame)
    cells = cell_rects(grid)
    for r in range(5):
        for c in range(5):
            label = board.cells[r][c] or "?"
            cell = cells[r][c]
            cv2.putText(vis, label[:3], (cell.x + 3, cell.y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            # save cell crops for template tuning
            patch = crop(frame, cell)
            cv2.imwrite(str(ROOT / "assets" / "templates" / f"cell_{r}_{c}.png"), patch)

    cv2.imwrite(str(ROOT / "assets" / "calibration" / "refined_preview.png"), vis)
    print("Saved", out)
    for row in board.cells:
        print(row)


if __name__ == "__main__":
    main()
