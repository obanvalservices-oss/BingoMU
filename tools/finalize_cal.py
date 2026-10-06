"""Write final calibration using confirmed ROIs and classify the board."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import crop
from src.types import Calibration, Rect
from src.vision.board import BoardReader, cell_rects
from src.vision.templates import DEFAULT_PROFILES, JewelClassifier

GRID = Rect(830, 318, 248, 248)
BOXES = Rect(790, 230, 70, 50)
AUTO = Rect(1090, 310, 90, 36)
DRAW = Rect(860, 230, 55, 50)
SCORE = Rect(1090, 500, 100, 40)
OVERLAY = Rect(760, 200, 450, 500)
START = Rect(900, 640, 160, 40)
REWARD = Rect(900, 660, 160, 40)


def main() -> None:
    profiles_path = ROOT / "assets" / "calibration" / "color_profiles.json"
    with profiles_path.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_PROFILES, f, indent=2)

    cal = Calibration(
        overlay=OVERLAY,
        grid=GRID,
        boxes=BOXES,
        auto_btn=AUTO,
        start_btn=START,
        reward_btn=REWARD,
        score_roi=SCORE,
        draw_jewel_roi=DRAW,
    )
    cal.save(str(ROOT / "assets" / "calibration" / "default.json"))

    frame = cv2.imread(str(ROOT / "assets" / "calibration" / "raw_35000.png"))
    clf = JewelClassifier(profiles=DEFAULT_PROFILES, min_score=0.05)
    reader = BoardReader(cal, clf)
    board = reader.read(frame)
    cells = cell_rects(GRID)
    tmpl = ROOT / "assets" / "templates"
    for p in tmpl.glob("*.png"):
        p.unlink()

    vis = frame.copy()
    for name, r in [("grid", GRID), ("boxes", BOXES), ("auto", AUTO), ("draw", DRAW)]:
        cv2.rectangle(vis, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 255, 255), 2)
        cv2.putText(vis, name, (r.x, max(15, r.y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    counts: dict[str, int] = {}
    for r in range(5):
        for c in range(5):
            label = board.cells[r][c]
            cell = cells[r][c]
            patch = crop(frame, cell)
            name = label or "unk"
            cv2.imwrite(str(tmpl / f"cell_{r}_{c}_{name}.png"), patch)
            cv2.putText(
                vis,
                name[:3],
                (cell.x + 2, cell.y + 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 255, 0),
                1,
            )
            if label and label != "FREE":
                n = counts.get(label, 0)
                counts[label] = n + 1
                if n == 0:
                    cv2.imwrite(str(tmpl / f"{label}.png"), patch)

    cv2.imwrite(str(tmpl / "_draw_roi.png"), crop(frame, DRAW))
    cv2.imwrite(str(tmpl / "_boxes_roi.png"), crop(frame, BOXES))
    cv2.imwrite(str(tmpl / "_auto_roi.png"), crop(frame, AUTO))
    cv2.imwrite(str(ROOT / "assets" / "calibration" / "final_preview.png"), vis)

    print("Board:")
    for row in board.cells:
        print(row)
    print("counts", counts)
    print("draw jewel:", clf.classify(crop(frame, DRAW)))


if __name__ == "__main__":
    main()
