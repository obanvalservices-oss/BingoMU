"""Dump candidate grid crops for manual ROI selection."""

from pathlib import Path
import cv2

ROOT = Path(__file__).resolve().parent.parent
frame = cv2.imread(str(ROOT / "assets" / "calibration" / "raw_35000.png"))
out = ROOT / "assets" / "calibration" / "candidates"
out.mkdir(exist_ok=True)

# MU window-ish region from earlier detection
candidates = [
    ("mu_window", 645, 183, 808, 634),
    ("bingo_guess_a", 760, 200, 420, 480),
    ("bingo_guess_b", 800, 220, 380, 450),
    ("grid_guess_a", 820, 280, 280, 280),
    ("grid_guess_b", 840, 300, 260, 260),
    ("grid_guess_c", 790, 270, 300, 300),
    ("grid_guess_d", 860, 320, 240, 240),
    ("top_boxes", 850, 200, 220, 60),
]

for name, x, y, w, h in candidates:
    crop = frame[y : y + h, x : x + w]
    cv2.imwrite(str(out / f"{name}.png"), crop)
    print("wrote", name, crop.shape)
