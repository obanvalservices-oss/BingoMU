"""
Guided calibration wizard (Mac + Windows).

  python tools/calibrate_wizard.py

Flow:
  1) Countdown → screenshot (bring Remote Desktop to front)
  2) Click each control (zoom/pan for precision)
  3) Saves assets/calibration/default.json

Keys while marking:
  + / =   zoom in
  -       zoom out
  arrows  pan
  r       restart points
  ENTER   save (when all done)
  q       quit
  mouse wheel = zoom toward cursor
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import ScreenCapture
from src.types import JEWEL_NAMES, JEWEL_TYPES, Calibration, Rect


CLICKS: list[tuple[str, str]] = [
    ("overlay_tl", "TOP-LEFT corner of the Jewel Bingo window"),
    ("overlay_br", "BOTTOM-RIGHT corner of the Jewel Bingo window"),
    ("grid_tl", "TOP-LEFT cell of the 5x5 grid (inside the cell)"),
    ("grid_br", "BOTTOM-RIGHT cell of the 5x5 grid"),
    ("auto_btn", "AUTO-PLACE button"),
    ("boxes", "BLUE CHEST / top-left box (the one we always pick)"),
    ("start_btn", "START GAME button (or where it appears)"),
    ("reward_btn", "GET REWARD / accept prize button"),
    ("draw_jewel_roi", "CURRENT DRAWN JEWEL icon area (during play)"),
    ("score_roi", "SCORE / remaining draws number area"),
]

for code in JEWEL_TYPES:
    CLICKS.append((f"jewel_{code}", f"Right-panel jewel: {code} — {JEWEL_NAMES[code]}"))


def rect_from_corners(tl: tuple[int, int], br: tuple[int, int]) -> Rect:
    x0, y0 = tl
    x1, y1 = br
    return Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


def point_as_small_rect(pt: tuple[int, int], half: int = 12) -> Rect:
    x, y = pt
    return Rect(x - half, y - half, half * 2, half * 2)


def build_calibration(pts: dict[str, tuple[int, int]]) -> Calibration:
    overlay = rect_from_corners(pts["overlay_tl"], pts["overlay_br"])
    grid = rect_from_corners(pts["grid_tl"], pts["grid_br"])
    jewel_btns = {code: point_as_small_rect(pts[f"jewel_{code}"]) for code in JEWEL_TYPES}
    return Calibration(
        overlay=overlay,
        grid=grid,
        boxes=point_as_small_rect(pts["boxes"], 16),
        auto_btn=point_as_small_rect(pts["auto_btn"], 18),
        start_btn=point_as_small_rect(pts["start_btn"], 20),
        reward_btn=point_as_small_rect(pts["reward_btn"], 20),
        score_roi=point_as_small_rect(pts["score_roi"], 20),
        draw_jewel_roi=point_as_small_rect(pts["draw_jewel_roi"], 18),
        jewel_btns=jewel_btns,
    )


def countdown_capture(delay: float) -> np.ndarray:
    """Wait so the user can bring Chrome Remote Desktop to the front."""
    delay = max(1.0, float(delay))
    print()
    print("=" * 56)
    print("  PREPARA LA CAPTURA")
    print("=" * 56)
    print("1) Pon Chrome Remote Desktop al FRENTE (Jewel Bingo visible).")
    print("2) Minimiza o mueve esta Terminal a un lado.")
    print("3) NO cubras el panel de Jewel Bingo.")
    print(f"4) Captura en {delay:.0f} segundos...")
    print("=" * 56)
    print()
    remaining = int(delay)
    while remaining > 0:
        print(f"  Capturando en {remaining}...", flush=True)
        time.sleep(1.0)
        remaining -= 1
    print("  ¡Capturando ahora!", flush=True)
    cap = ScreenCapture()
    frame = cap.grab()
    cap.close()
    return frame


class ZoomView:
    """Full-res screenshot with zoom + pan. Points stored in original coords."""

    def __init__(self, frame: np.ndarray, view_w: int = 1600, view_h: int = 1000) -> None:
        self.frame = frame
        self.fh, self.fw = frame.shape[:2]
        self.view_w = min(view_w, self.fw)
        self.view_h = min(view_h, self.fh)
        self.zoom = 1.0
        self.ox = 0  # top-left of viewport in original coords
        self.oy = 0
        self.idx = 0
        self.points: dict[str, tuple[int, int]] = {}
        self._drag = False
        self._last = (0, 0)

    def _clamp_pan(self) -> None:
        vw = max(1, int(self.view_w / self.zoom))
        vh = max(1, int(self.view_h / self.zoom))
        self.ox = int(np.clip(self.ox, 0, max(0, self.fw - vw)))
        self.oy = int(np.clip(self.oy, 0, max(0, self.fh - vh)))

    def set_zoom(self, z: float, focus_view: tuple[int, int] | None = None) -> None:
        z = float(np.clip(z, 1.0, 8.0))
        if focus_view is not None:
            # keep the image point under cursor stable
            fx, fy = self.view_to_orig(*focus_view)
            self.zoom = z
            self.ox = int(fx - focus_view[0] / self.zoom)
            self.oy = int(fy - focus_view[1] / self.zoom)
        else:
            # zoom toward viewport center
            cx, cy = self.view_to_orig(self.view_w // 2, self.view_h // 2)
            self.zoom = z
            self.ox = int(cx - (self.view_w // 2) / self.zoom)
            self.oy = int(cy - (self.view_h // 2) / self.zoom)
        self._clamp_pan()

    def pan(self, dx: int, dy: int) -> None:
        self.ox += int(dx / self.zoom)
        self.oy += int(dy / self.zoom)
        self._clamp_pan()

    def view_to_orig(self, vx: int, vy: int) -> tuple[int, int]:
        x = int(self.ox + vx / self.zoom)
        y = int(self.oy + vy / self.zoom)
        return (
            int(np.clip(x, 0, self.fw - 1)),
            int(np.clip(y, 0, self.fh - 1)),
        )

    def orig_to_view(self, x: int, y: int) -> tuple[int, int] | None:
        vx = int((x - self.ox) * self.zoom)
        vy = int((y - self.oy) * self.zoom)
        if 0 <= vx < self.view_w and 0 <= vy < self.view_h:
            return vx, vy
        return None

    def focus_on_overlay(self) -> None:
        if "overlay_tl" not in self.points or "overlay_br" not in self.points:
            return
        x0, y0 = self.points["overlay_tl"]
        x1, y1 = self.points["overlay_br"]
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        pad = 40
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(self.fw - 1, x1 + pad)
        y1 = min(self.fh - 1, y1 + pad)
        ow, oh = max(1, x1 - x0), max(1, y1 - y0)
        zx = self.view_w / ow
        zy = self.view_h / oh
        self.zoom = float(np.clip(min(zx, zy), 1.0, 8.0))
        self.ox = x0
        self.oy = y0
        self._clamp_pan()
        print(f"  Zoom auto → panel Jewel Bingo ({self.zoom:.1f}x)")

    def render(self) -> np.ndarray:
        vw = max(1, int(self.view_w / self.zoom))
        vh = max(1, int(self.view_h / self.zoom))
        self._clamp_pan()
        crop = self.frame[self.oy : self.oy + vh, self.ox : self.ox + vw]
        view = cv2.resize(crop, (self.view_w, self.view_h), interpolation=cv2.INTER_NEAREST)

        # draw marks
        for k, (x, y) in self.points.items():
            pt = self.orig_to_view(x, y)
            if pt is None:
                continue
            cv2.circle(view, pt, max(4, int(5 * min(self.zoom, 3))), (0, 255, 0), -1)
            cv2.putText(view, k, (pt[0] + 8, pt[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        if "overlay_tl" in self.points and "overlay_br" in self.points:
            a = self.orig_to_view(*self.points["overlay_tl"])
            b = self.orig_to_view(*self.points["overlay_br"])
            if a and b:
                cv2.rectangle(view, a, b, (255, 128, 0), 2)
        if "grid_tl" in self.points and "grid_br" in self.points:
            a = self.orig_to_view(*self.points["grid_tl"])
            b = self.orig_to_view(*self.points["grid_br"])
            if a and b:
                cv2.rectangle(view, a, b, (0, 255, 255), 2)

        # banner
        cv2.rectangle(view, (0, 0), (view.shape[1], 48), (0, 0, 0), -1)
        if self.idx < len(CLICKS):
            msg = f"[{self.idx+1}/{len(CLICKS)}] {CLICKS[self.idx][1]}"
        else:
            msg = "Listo. ENTER=guardar  r=reiniciar  q=salir"
        cv2.putText(view, msg, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        help_line = f"zoom={self.zoom:.1f}x   +/-=zoom  flechas=mover  rueda=zoom  r=reiniciar"
        cv2.putText(view, help_line, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
        return view

    def on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_MOUSEWHEEL:
            delta = 1 if flags > 0 else -1
            # Windows/macOS wheel encoding varies; also handle EVENT_MOUSEHWHEEL fallback via flags
            if flags < 0:
                delta = -1
            self.set_zoom(self.zoom * (1.25 if delta > 0 else 0.8), focus_view=(x, y))
            return

        if event == cv2.EVENT_MBUTTONDOWN or (event == cv2.EVENT_RBUTTONDOWN):
            self._drag = True
            self._last = (x, y)
            return
        if event in (cv2.EVENT_MBUTTONUP, cv2.EVENT_RBUTTONUP):
            self._drag = False
            return
        if event == cv2.EVENT_MOUSEMOVE and self._drag:
            dx = self._last[0] - x
            dy = self._last[1] - y
            self.pan(dx, dy)
            self._last = (x, y)
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            if self.idx >= len(CLICKS):
                return
            ox, oy = self.view_to_orig(x, y)
            key = CLICKS[self.idx][0]
            self.points[key] = (ox, oy)
            self.idx += 1
            print(f"  OK {key} @ screen ({ox},{oy})  zoom={self.zoom:.1f}x")
            # After both overlay corners, auto-zoom into the panel
            if key == "overlay_br":
                self.focus_on_overlay()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "assets" / "calibration" / "default.json")
    ap.add_argument(
        "--delay",
        type=float,
        default=8.0,
        help="Seconds before screenshot (time to bring Remote Desktop to front)",
    )
    ap.add_argument("--view-w", type=int, default=1600)
    ap.add_argument("--view-h", type=int, default=1000)
    args = ap.parse_args()

    frame = countdown_capture(args.delay)
    view = ZoomView(frame, view_w=args.view_w, view_h=args.view_h)

    win = "Jewel Bingo Calibration — zoom con + / - / rueda"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, view.view_w, view.view_h)
    cv2.setMouseCallback(win, view.on_mouse)

    print()
    print("Marca cada punto. Puedes AGRANDAR la imagen:")
    print("  + o =     zoom in")
    print("  -         zoom out")
    print("  flechas   mover / pan")
    print("  rueda     zoom hacia el cursor")
    print("  click der. arrastrar para mover")
    print("  r         reiniciar")
    print("  ENTER     guardar (al terminar los 16)")
    print("  q         salir")
    print()

    while True:
        img = view.render()
        cv2.imshow(win, img)
        key = cv2.waitKeyEx(20)
        if key == -1:
            continue
        # OpenCV key codes
        code = key & 0xFF
        if code == ord("q"):
            cv2.destroyAllWindows()
            return 1
        if code == ord("r"):
            view.idx = 0
            view.points.clear()
            view.zoom = 1.0
            view.ox = view.oy = 0
            print("Reiniciado.")
        if code in (ord("+"), ord("=")):
            view.set_zoom(view.zoom * 1.25)
        if code == ord("-"):
            view.set_zoom(view.zoom / 1.25)
        # arrows (platform-dependent)
        if key in (65362, 2490368, 63232):  # up
            view.pan(0, -80)
        if key in (65364, 2621440, 63233):  # down
            view.pan(0, 80)
        if key in (65361, 2424832, 63234):  # left
            view.pan(-80, 0)
        if key in (65363, 2555904, 63235):  # right
            view.pan(80, 0)
        if code == 13 and view.idx >= len(CLICKS):
            break

    cv2.destroyAllWindows()

    cal = build_calibration(view.points)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cal.save(str(args.out))
    # also save a preview for debugging
    preview_path = args.out.parent / "cal_preview.png"
    prev = frame.copy()
    for k, (x, y) in view.points.items():
        cv2.circle(prev, (x, y), 6, (0, 255, 0), -1)
        cv2.putText(prev, k, (x + 6, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 255), 1)
    cv2.imwrite(str(preview_path), prev)

    # Capture jewel panel crops as match templates (much better than color-only)
    from src.vision.templates import save_jewel_templates_from_frame

    tmpl_dir = ROOT / "assets" / "templates"
    print("\nGuardando plantillas de joyas (panel derecho)...")
    saved = save_jewel_templates_from_frame(frame, cal, tmpl_dir)
    print(f"Templates: {saved}")

    print(f"\nSaved calibration → {args.out}")
    print(f"Preview → {preview_path}")
    print("Jewel buttons:", list(cal.jewel_btns.keys()))
    print("\nIMPORTANTE: las plantillas B/S/CR/H/L/C.png se usan para reconocer el sorteo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
