"""
Live calibration overlay at REAL screen size (1:1).

Shows boxes exactly where the bot clicks. Move Chrome Remote Desktop until
the GRID / buttons line up with the game, then Q / ESC to close.

  python tools/show_calibration.py
  python tools/show_calibration.py --cal assets/calibration/default.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from src.capture import ScreenCapture
from src.types import Calibration, Rect

# BGR colors
COLORS = {
    "overlay": (255, 200, 0),
    "grid": (0, 220, 0),
    "boxes": (255, 80, 40),
    "auto_btn": (0, 220, 255),
    "start_btn": (0, 180, 255),
    "reward_btn": (180, 0, 255),
    "score_roi": (255, 0, 200),
    "draw_jewel_roi": (0, 140, 255),
    "jewel": (255, 255, 255),
}

WIN = "JewelBingo Calibration 1:1 — mueve RD | R refresca | F pantalla | Q cierra"


def _draw_rect(
    img: np.ndarray, rect: Rect, color: tuple[int, int, int], label: str, thick: int = 2
) -> None:
    x, y, w, h = rect.x, rect.y, rect.w, rect.h
    H, W = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W - 1, x + w), min(H - 1, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    cv2.rectangle(img, (x0, y0), (x1, y1), color, thick)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    ly = max(th + 4, y0 - 4)
    cv2.rectangle(img, (x0, ly - th - 4), (x0 + tw + 4, ly + 2), color, -1)
    cv2.putText(
        img, label, (x0 + 2, ly - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA
    )


def _draw_grid_cells(img: np.ndarray, grid: Rect, color: tuple[int, int, int]) -> None:
    for i in range(6):
        x = int(grid.x + i * grid.w / 5)
        y = int(grid.y + i * grid.h / 5)
        cv2.line(img, (x, grid.y), (x, grid.y + grid.h), color, 1)
        cv2.line(img, (grid.x, y), (grid.x + grid.w, y), color, 1)
    cx = int(grid.x + 2.5 * grid.w / 5)
    cy = int(grid.y + 2.5 * grid.h / 5)
    cv2.circle(img, (cx, cy), 8, (0, 255, 255), 2)


def paint_calibration(frame: np.ndarray, cal: Calibration) -> np.ndarray:
    out = frame.copy()
    _draw_rect(out, cal.overlay, COLORS["overlay"], "OVERLAY", 2)
    _draw_rect(out, cal.grid, COLORS["grid"], "GRID 5x5", 3)
    _draw_grid_cells(out, cal.grid, COLORS["grid"])
    _draw_rect(out, cal.boxes, COLORS["boxes"], "BOXES (azul)", 2)
    _draw_rect(out, cal.auto_btn, COLORS["auto_btn"], "AUTO", 2)
    _draw_rect(out, cal.start_btn, COLORS["start_btn"], "START", 2)
    _draw_rect(out, cal.reward_btn, COLORS["reward_btn"], "REWARD", 2)
    _draw_rect(out, cal.score_roi, COLORS["score_roi"], "SCORE", 2)
    _draw_rect(out, cal.draw_jewel_roi, COLORS["draw_jewel_roi"], "DRAWN JEWEL", 2)
    for code, rect in (cal.jewel_btns or {}).items():
        _draw_rect(out, rect, COLORS["jewel"], f"J-{code}", 1)

    h, w = out.shape[:2]
    tip = (
        f"1:1 REAL {w}x{h}  |  Mueve Chrome Remote Desktop hasta que GRID coincida  "
        f"|  R=refrescar  F=fullscreen  Q/ESC=cerrar"
    )
    cv2.rectangle(out, (0, 0), (w, 32), (0, 0, 0), -1)
    cv2.putText(
        out, tip, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA
    )
    return out


def _show(win: str, vis: np.ndarray, *, fullscreen: bool, fit: bool) -> None:
    h, w = vis.shape[:2]
    show = vis
    if fit:
        max_w = 1400
        if w > max_w:
            scale = max_w / w
            show = cv2.resize(vis, (int(w * scale), int(h * scale)))
    cv2.imshow(win, show)
    if not fit:
        # Force 1:1 window size matching capture pixels
        try:
            cv2.resizeWindow(win, w, h)
            cv2.moveWindow(win, 0, 0)
        except Exception:
            pass
    try:
        cv2.setWindowProperty(
            win,
            cv2.WND_PROP_FULLSCREEN,
            cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL,
        )
    except Exception:
        pass


def _grab_clean(cap: ScreenCapture, win: str) -> np.ndarray:
    """Hide overlay briefly so the screenshot is the real desktop (RD + game)."""
    try:
        cv2.destroyWindow(win)
        cv2.waitKey(1)
    except Exception:
        pass
    time.sleep(0.12)
    frame = cap.grab()
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
    except Exception:
        pass
    return frame


def main() -> int:
    p = argparse.ArgumentParser(description="Show calibration boxes at real 1:1 screen size")
    p.add_argument(
        "--cal",
        type=Path,
        default=ROOT / "assets" / "calibration" / "default.json",
    )
    p.add_argument(
        "--interval",
        type=float,
        default=0.0,
        help="Auto-refresh seconds (0 = only manual R). Default 0.",
    )
    p.add_argument(
        "--fit",
        action="store_true",
        help="Scale down to fit (NOT for alignment — use default 1:1)",
    )
    p.add_argument(
        "--windowed",
        action="store_true",
        help="Start windowed instead of fullscreen",
    )
    p.add_argument(
        "--save",
        type=Path,
        default=None,
        help="Write one PNG preview and exit",
    )
    args = p.parse_args()

    if not args.cal.exists():
        print(f"No calibration: {args.cal}")
        print("Run calibrate wizard first.")
        return 1

    cal = Calibration.load(str(args.cal))
    cap = ScreenCapture()
    fullscreen = not args.windowed and not args.fit

    print("Calibration preview @ REAL SIZE (1:1)")
    print(f"  cal: {args.cal}")
    print("  Move Chrome Remote Desktop until GRID/buttons match the game.")
    print("  R = refresh (hides overlay, grabs clean screen)")
    print("  F = toggle fullscreen | Q / ESC = close")

    # First grab before any window exists
    frame = cap.grab()
    vis = paint_calibration(frame, cal)
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    try:
        cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1)
    except Exception:
        pass
    _show(WIN, vis, fullscreen=fullscreen, fit=args.fit)

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.save), paint_calibration(frame, cal))
        print(f"Saved {args.save}")
        cap.close()
        cv2.destroyAllWindows()
        return 0

    last = time.time()
    try:
        while True:
            wait_ms = 50
            if args.interval > 0:
                wait_ms = max(1, int(args.interval * 1000))
            key = cv2.waitKey(wait_ms) & 0xFF

            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("f"), ord("F")):
                fullscreen = not fullscreen
                _show(WIN, vis, fullscreen=fullscreen, fit=args.fit)
                continue
            if key in (ord("r"), ord("R")) or (
                args.interval > 0 and time.time() - last >= args.interval
            ):
                frame = _grab_clean(cap, WIN)
                vis = paint_calibration(frame, cal)
                _show(WIN, vis, fullscreen=fullscreen, fit=args.fit)
                last = time.time()
    finally:
        cap.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
