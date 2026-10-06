"""Locate the colorful 5x5 jewel grid by scanning for high-saturation patches."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.types import Calibration, Rect
from src.vision.board import BoardReader
from src.vision.templates import JewelClassifier
from src.capture import crop


def saturation_map(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)
    # colorful + reasonably bright
    return (s / 255.0) * (v / 255.0)


def find_grid(frame: np.ndarray) -> Rect:
    h, w = frame.shape[:2]
    score = saturation_map(frame)
    # Integral image for fast window sums
    integ = cv2.integral(score)
    best = None
    best_val = -1.0
    # Expected grid size relative to 1920x1080 phone capture of windowed MU
    for size in range(220, 420, 10):
        for y in range(80, h - size - 40, 8):
            for x in range(400, w - size - 40, 8):
                # mean saturation in square
                a = integ[y, x]
                b = integ[y, x + size]
                c = integ[y + size, x]
                d = integ[y + size, x + size]
                mean = (d - b - c + a) / (size * size)
                # Prefer more central-ish x (MU is centered-right)
                center_bonus = 1.0 - abs((x + size / 2) - w * 0.55) / w
                val = mean * (0.7 + 0.3 * center_bonus)
                if val > best_val:
                    best_val = val
                    best = Rect(x, y, size, size)
    assert best is not None
    print("best grid", best, "score", best_val)
    return best


def main() -> None:
    frame = cv2.imread(str(ROOT / "assets" / "calibration" / "raw_35000.png"))
    if frame is None:
        raise SystemExit("missing raw_35000.png — run tools/_dump_frames.py")

    grid = find_grid(frame)
    # Expand slightly inward margins are better — shrink 4%
    m = int(grid.w * 0.02)
    grid = Rect(grid.x + m, grid.y + m, grid.w - 2 * m, grid.h - 2 * m)

    # Derive related ROIs from grid geometry (from observed UI layout)
    # Top boxes sit just above the grid
    boxes = Rect(grid.x + int(grid.w * 0.15), grid.y - 70, int(grid.w * 0.55), 55)
    # Auto button to the right-top of grid
    auto_btn = Rect(grid.x + grid.w + 10, grid.y, 100, 36)
    # Jewel legend / blink column right of grid
    draw_jewel_roi = Rect(grid.x + grid.w + 8, grid.y + 50, 110, 200)
    score_roi = Rect(grid.x + grid.w + 8, grid.y + grid.h - 40, 110, 40)
    overlay = Rect(grid.x - 40, grid.y - 100, grid.w + 200, grid.h + 220)
    start_btn = Rect(grid.x + int(grid.w * 0.3), grid.y + grid.h + 80, 160, 40)
    reward_btn = Rect(grid.x + int(grid.w * 0.3), grid.y + grid.h + 100, 160, 40)

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
    cal.save(str(ROOT / "assets" / "calibration" / "default.json"))

    vis = frame.copy()
    for name, r in [
        ("grid", grid),
        ("boxes", boxes),
        ("auto", auto_btn),
        ("draw", draw_jewel_roi),
    ]:
        cv2.rectangle(vis, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 255, 255), 2)
        cv2.putText(vis, name, (r.x, max(15, r.y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    reader = BoardReader(cal, JewelClassifier())
    board = reader.read(frame)
    from src.vision.board import cell_rects

    cells = cell_rects(grid)
    tmpl = ROOT / "assets" / "templates"
    # clear old cell crops
    for p in tmpl.glob("cell_*.png"):
        p.unlink()
    counts: dict[str, int] = {}
    for r in range(5):
        for c in range(5):
            label = board.cells[r][c] or "?"
            cell = cells[r][c]
            patch = crop(frame, cell)
            cv2.imwrite(str(tmpl / f"cell_{r}_{c}_{label}.png"), patch)
            cv2.putText(vis, label[:3], (cell.x + 2, cell.y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            if label and label != "FREE" and label != "?":
                n = counts.get(label, 0)
                counts[label] = n + 1
                if n == 0:
                    cv2.imwrite(str(tmpl / f"{label}.png"), patch)

    cv2.imwrite(str(ROOT / "assets" / "calibration" / "sat_grid_preview.png"), vis)
    print("Board:")
    for row in board.cells:
        print(row)
    print("counts", counts)


if __name__ == "__main__":
    main()
