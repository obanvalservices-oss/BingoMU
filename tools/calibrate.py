"""
Interactive calibration tool.

Usage:
  python tools/calibrate.py
  python tools/calibrate.py --image snapshot.png
  python tools/calibrate.py --video path/to.mp4 --ms 35000

Click-drag to define regions in order prompted. Press ENTER to confirm each ROI,
'r' to redo, 'q' to quit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import ScreenCapture, VideoCapture
from src.types import Calibration, Rect

ROI_ORDER = [
    ("overlay", "Jewel Bingo overlay window"),
    ("grid", "5x5 jewel grid"),
    ("boxes", "Box / Event Inventory area"),
    ("auto_btn", "AUTO button"),
    ("start_btn", "START GAME button"),
    ("reward_btn", "Accept reward / OK button"),
    ("score_roi", "Total Score text region"),
    ("draw_jewel_roi", "Drawn / blinking jewel region"),
]


class ROIPicker:
    def __init__(self, image: np.ndarray, title: str) -> None:
        self.base = image.copy()
        self.title = title
        self.drawing = False
        self.ix = self.iy = 0
        self.rect: Rect | None = None
        self._tmp = image.copy()

    def _on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.ix, self.iy = x, y
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self._tmp = self.base.copy()
            cv2.rectangle(self._tmp, (self.ix, self.iy), (x, y), (0, 255, 0), 2)
        elif event == cv2.EVENT_LBUTTONUP:
            self.drawing = False
            x0, y0 = min(self.ix, x), min(self.iy, y)
            w, h = abs(x - self.ix), abs(y - self.iy)
            if w > 2 and h > 2:
                self.rect = Rect(x0, y0, w, h)
                self._tmp = self.base.copy()
                cv2.rectangle(self._tmp, (x0, y0), (x0 + w, y0 + h), (0, 255, 0), 2)

    def pick(self) -> Rect | None:
        cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.title, self._on_mouse)
        self._tmp = self.base.copy()
        while True:
            cv2.imshow(self.title, self._tmp)
            key = cv2.waitKey(20) & 0xFF
            if key == ord("q"):
                cv2.destroyWindow(self.title)
                return None
            if key == ord("r"):
                self.rect = None
                self._tmp = self.base.copy()
            if key == 13:  # Enter
                if self.rect:
                    cv2.destroyWindow(self.title)
                    return self.rect


def load_frame(args: argparse.Namespace) -> np.ndarray:
    if args.image:
        img = cv2.imread(str(args.image))
        if img is None:
            raise SystemExit(f"Cannot read image: {args.image}")
        return img
    if args.video:
        vc = VideoCapture(args.video)
        frame = vc.seek_ms(args.ms)
        vc.close()
        if frame is None:
            raise SystemExit("Failed to seek video frame")
        return frame
    print("Capturing primary monitor in 2 seconds...")
    import time

    time.sleep(2)
    cap = ScreenCapture()
    frame = cap.grab()
    cap.close()
    return frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, default=None)
    ap.add_argument("--video", type=Path, default=ROOT / "VID_20261006_094447.mp4")
    ap.add_argument("--ms", type=float, default=35000.0)
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "assets" / "calibration" / "default.json",
    )
    ap.add_argument("--window-title", default="Chrome Remote Desktop")
    args = ap.parse_args()

    frame = load_frame(args)
    # Scale down if huge for easier picking
    display = frame
    scale = 1.0
    h, w = frame.shape[:2]
    max_w = 1400
    if w > max_w:
        scale = max_w / w
        display = cv2.resize(frame, (int(w * scale), int(h * scale)))

    rects: dict[str, Rect] = {}
    for key, label in ROI_ORDER:
        print(f"Draw ROI for: {label}  [drag, Enter=ok, r=redo, q=quit]")
        picker = ROIPicker(display, label)
        r = picker.pick()
        if r is None:
            print("Cancelled.")
            return 1
        # Map back to original coordinates
        if scale != 1.0:
            r = Rect(
                int(r.x / scale),
                int(r.y / scale),
                int(r.w / scale),
                int(r.h / scale),
            )
        rects[key] = r
        # Draw confirmed on next base
        cv2.rectangle(
            display,
            (int(r.x * scale), int(r.y * scale)),
            (int((r.x + r.w) * scale), int((r.y + r.h) * scale)),
            (255, 128, 0),
            2,
        )

    cal = Calibration(
        overlay=rects["overlay"],
        grid=rects["grid"],
        boxes=rects["boxes"],
        auto_btn=rects["auto_btn"],
        start_btn=rects["start_btn"],
        reward_btn=rects["reward_btn"],
        score_roi=rects["score_roi"],
        draw_jewel_roi=rects["draw_jewel_roi"],
        window_title=args.window_title,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cal.save(str(args.out))
    print(f"Saved calibration -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
