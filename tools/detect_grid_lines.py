"""Detect exact 5x5 cell bounds via dark grid lines inside the bingo panel."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import crop
from src.types import Calibration, Rect
from src.vision.board import BoardReader, cell_rects
from src.vision.templates import DEFAULT_PROFILES, JewelClassifier


def main() -> None:
    frame = cv2.imread(str(ROOT / "assets" / "calibration" / "raw_35000.png"))
    # Known good panel crop that contains the grid
    panel = Rect(820, 280, 280, 280)
    roi = crop(frame, panel)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # Emphasize bright cell borders
    edges = cv2.Canny(gray, 50, 150)
    # Horizontal / vertical projection to find grid lines
    row_energy = edges.mean(axis=1)
    col_energy = edges.mean(axis=0)

    def peaks(arr, min_dist=15, top_n=6):
        idxs = []
        work = arr.copy()
        for _ in range(top_n):
            i = int(np.argmax(work))
            if work[i] <= 0:
                break
            idxs.append(i)
            lo, hi = max(0, i - min_dist), min(len(work), i + min_dist + 1)
            work[lo:hi] = 0
        return sorted(idxs)

    rows = peaks(row_energy, min_dist=20, top_n=8)
    cols = peaks(col_energy, min_dist=20, top_n=8)
    print("row peaks", rows, "vals", [float(row_energy[i]) for i in rows])
    print("col peaks", cols, "vals", [float(col_energy[i]) for i in cols])

    # Pick 6 consecutive peaks that are most evenly spaced
    def best_six(peaks_list):
        if len(peaks_list) < 6:
            return peaks_list
        best = None
        best_score = 1e9
        for i in range(len(peaks_list) - 5):
            seq = peaks_list[i : i + 6]
            gaps = np.diff(seq)
            score = float(np.std(gaps))
            if score < best_score and np.mean(gaps) > 25:
                best_score = score
                best = seq
        return best or peaks_list[:6]

    rs = best_six(rows)
    cs = best_six(cols)
    print("chosen rows", rs, "cols", cs)

    if rs and cs and len(rs) >= 2 and len(cs) >= 2:
        top, bottom = rs[0], rs[-1]
        left, right = cs[0], cs[-1]
        grid = Rect(panel.x + left, panel.y + top, right - left, bottom - top)
    else:
        grid = Rect(835, 330, 230, 230)

    print("grid", grid)

    boxes = Rect(panel.x + 10, panel.y + 5, 60, 45)
    draw = Rect(panel.x + 70, panel.y + 5, 50, 45)
    auto = Rect(panel.x + panel.w - 5, panel.y + 40, 90, 35)
    # auto is outside panel — place to the right of MU bingo window
    auto = Rect(1105, 310, 90, 35)
    cal = Calibration(
        overlay=Rect(760, 200, 450, 500),
        grid=grid,
        boxes=boxes,
        auto_btn=auto,
        start_btn=Rect(900, 640, 160, 40),
        reward_btn=Rect(900, 660, 160, 40),
        score_roi=Rect(1105, 500, 100, 40),
        draw_jewel_roi=draw,
    )
    cal.save(str(ROOT / "assets" / "calibration" / "default.json"))

    # visualize peaks
    vis = roi.copy()
    for y in rs or []:
        cv2.line(vis, (0, y), (roi.shape[1] - 1, y), (0, 255, 0), 1)
    for x in cs or []:
        cv2.line(vis, (x, 0), (x, roi.shape[0] - 1), (255, 0, 0), 1)
    cv2.imwrite(str(ROOT / "assets" / "calibration" / "grid_lines.png"), vis)

    clf = JewelClassifier(profiles=DEFAULT_PROFILES, min_score=0.04)
    reader = BoardReader(cal, clf)
    board = reader.read(frame)
    cells = cell_rects(grid)
    tmpl = ROOT / "assets" / "templates"
    for p in tmpl.glob("*.png"):
        p.unlink()
    full = frame.copy()
    cv2.rectangle(full, (grid.x, grid.y), (grid.x + grid.w, grid.y + grid.h), (0, 255, 255), 2)
    counts: dict[str, int] = {}
    for r in range(5):
        for c in range(5):
            label = board.cells[r][c] or "unk"
            patch = crop(frame, cells[r][c])
            cv2.imwrite(str(tmpl / f"cell_{r}_{c}_{label}.png"), patch)
            cv2.putText(
                full,
                label[:3],
                (cells[r][c].x + 2, cells[r][c].y + 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 255, 0),
                1,
            )
            if label not in ("FREE", "unk"):
                counts[label] = counts.get(label, 0) + 1
                if counts[label] == 1:
                    cv2.imwrite(str(tmpl / f"{label}.png"), patch)
    cv2.imwrite(str(ROOT / "assets" / "calibration" / "final_preview.png"), full)
    print("Board:")
    for row in board.cells:
        print(row)
    print("counts", counts)
    print("draw", clf.classify(crop(frame, cal.draw_jewel_roi)))


if __name__ == "__main__":
    main()
