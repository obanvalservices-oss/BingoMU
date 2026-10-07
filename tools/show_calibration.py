"""
Transparent calibration OVERLAY (see Chrome / RD underneath).

Default: glass overlay with only boxes — not a screenshot.
  python tools/show_calibration.py
  python tools/show_calibration.py --screenshot   # old print-screen mode

Keys: Q/ESC quit | SPACE hide/show (to drag RD) | R redraw
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from src.types import Calibration, Rect

# Outline colors (Tk hex)
COLORS = {
    "overlay": "#ffc800",
    "grid": "#00ff66",
    "boxes": "#ff5028",
    "auto_btn": "#00dcff",
    "start_btn": "#00b4ff",
    "reward_btn": "#b400ff",
    "score_roi": "#ff00c8",
    "draw_jewel_roi": "#008cff",
    "jewel": "#ffffff",
}


def _scale_for_tk(root) -> float:
    """mss pixels / Tk points (Retina often 2.0). Calibration is in mss/pixel space."""
    try:
        import mss

        with mss.mss() as sct:
            mon = sct.monitors[1]
            sw = float(root.winfo_screenwidth())
            if sw > 0:
                s = mon["width"] / sw
                if 0.5 <= s <= 4.0:
                    return s
    except Exception:
        pass
    return 1.0


def _r(rect: Rect, scale: float) -> tuple[int, int, int, int]:
    return (
        int(rect.x / scale),
        int(rect.y / scale),
        int(rect.w / scale),
        int(rect.h / scale),
    )


def _mac_clickthrough() -> bool:
    """Let mouse pass through to Chrome/RD (subprocess-only NSApp)."""
    try:
        from AppKit import NSApp  # type: ignore

        app = NSApp.sharedApplication()
        ok = False
        for w in app.windows():
            try:
                w.setIgnoresMouseEvents_(True)
                # NSFloatingWindowLevel = 3
                w.setLevel_(3)
                ok = True
            except Exception:
                pass
        return ok
    except Exception:
        return False


def run_transparent(cal: Calibration) -> int:
    import tkinter as tk

    root = tk.Tk()
    root.title("JewelBingo Overlay")
    root.overrideredirect(True)
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{sw}x{sh}+0+0")
    root.lift()
    root.attributes("-topmost", True)

    if sys.platform == "darwin":
        try:
            root.wm_attributes("-transparent", True)
        except Exception:
            pass
        root.configure(bg="systemTransparent")
        canvas_bg = "systemTransparent"
    else:
        # Windows: chroma-key
        key = "#010101"
        try:
            root.attributes("-transparentcolor", key)
        except Exception:
            root.attributes("-alpha", 0.35)
        root.configure(bg=key)
        canvas_bg = key

    canvas = tk.Canvas(
        root, bg=canvas_bg, highlightthickness=0, bd=0, cursor="arrow",
    )
    canvas.pack(fill="both", expand=True)

    scale = _scale_for_tk(root)
    hidden = {"v": False}
    clickthrough = {"v": False}

    def draw() -> None:
        canvas.delete("all")
        s = scale

        def box(rect: Rect, color: str, label: str, width: int = 3) -> None:
            x, y, w, h = _r(rect, s)
            canvas.create_rectangle(
                x, y, x + w, y + h, outline=color, width=width, fill="",
            )
            canvas.create_text(
                x + 4, max(12, y - 6), text=label, fill=color, anchor="sw",
                font=("Helvetica", 12, "bold"),
            )

        box(cal.overlay, COLORS["overlay"], "OVERLAY", 2)
        box(cal.grid, COLORS["grid"], "GRID 5x5", 3)
        gx, gy, gw, gh = _r(cal.grid, s)
        for i in range(6):
            x = int(gx + i * gw / 5)
            y = int(gy + i * gh / 5)
            canvas.create_line(x, gy, x, gy + gh, fill=COLORS["grid"], width=1)
            canvas.create_line(gx, y, gx + gw, y, fill=COLORS["grid"], width=1)
        cx = int(gx + 2.5 * gw / 5)
        cy = int(gy + 2.5 * gh / 5)
        canvas.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, outline="#ffff00", width=2)

        box(cal.boxes, COLORS["boxes"], "BOXES", 2)
        box(cal.auto_btn, COLORS["auto_btn"], "AUTO", 2)
        box(cal.start_btn, COLORS["start_btn"], "START", 2)
        box(cal.reward_btn, COLORS["reward_btn"], "REWARD", 2)
        box(cal.score_roi, COLORS["score_roi"], "SCORE", 2)
        box(cal.draw_jewel_roi, COLORS["draw_jewel_roi"], "DRAWN", 2)
        for code, rect in (cal.jewel_btns or {}).items():
            box(rect, COLORS["jewel"], f"J-{code}", 1)

        tip = (
            f"OVERLAY transparente 1:1 (scale={s:.2f})  |  "
            "Mueve Chrome RD debajo  |  SPACE=ocultar/mostrar  |  Q=cerrar"
        )
        if not clickthrough["v"]:
            tip += "  |  (sin click-through: SPACE para arrastrar RD)"
        canvas.create_text(
            12, 18, text=tip, fill="#ffff00", anchor="nw",
            font=("Helvetica", 13, "bold"),
        )

    def quit_app(_event=None) -> None:
        root.destroy()

    def toggle_hide(_event=None) -> None:
        if hidden["v"]:
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            hidden["v"] = False
            root.after(50, lambda: _mac_clickthrough())
        else:
            root.withdraw()
            hidden["v"] = True

    def redraw(_event=None) -> None:
        nonlocal scale
        scale = _scale_for_tk(root)
        draw()

    root.bind("<Escape>", quit_app)
    root.bind("q", quit_app)
    root.bind("Q", quit_app)
    root.bind("<space>", toggle_hide)
    root.bind("r", redraw)
    root.bind("R", redraw)

    draw()
    root.update_idletasks()
    root.after(100, lambda: None)
    clickthrough["v"] = _mac_clickthrough()
    # Re-apply after map (Tk sometimes recreates the NSWindow)
    root.after(300, lambda: clickthrough.__setitem__("v", _mac_clickthrough()))
    root.after(800, lambda: clickthrough.__setitem__("v", _mac_clickthrough()))

    print("Transparent overlay ON — you should see Chrome underneath the boxes.")
    print(f"  scale mss/Tk = {scale:.2f}")
    print("  SPACE = hide/show (drag RD) | R = redraw | Q/ESC = close")
    if not clickthrough["v"]:
        print("  Tip: install pyobjc for click-through: pip install pyobjc-framework-Cocoa")

    root.mainloop()
    return 0


def run_screenshot(cal: Calibration, fit: bool, fullscreen: bool) -> int:
    """Legacy: screenshot + boxes (opaque)."""
    import cv2
    import numpy as np

    from src.capture import ScreenCapture

    # reuse previous paint helpers inline
    def paint(frame: np.ndarray) -> np.ndarray:
        out = frame.copy()

        def rect(r: Rect, color, label, thick=2):
            x0, y0 = max(0, r.x), max(0, r.y)
            x1, y1 = min(out.shape[1] - 1, r.x + r.w), min(out.shape[0] - 1, r.y + r.h)
            if x1 <= x0 or y1 <= y0:
                return
            cv2.rectangle(out, (x0, y0), (x1, y1), color, thick)
            cv2.putText(
                out, label, (x0 + 2, max(16, y0 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
            )

        rect(cal.overlay, (255, 200, 0), "OVERLAY")
        rect(cal.grid, (0, 220, 0), "GRID", 3)
        rect(cal.boxes, (255, 80, 40), "BOXES")
        rect(cal.auto_btn, (0, 220, 255), "AUTO")
        rect(cal.start_btn, (0, 180, 255), "START")
        rect(cal.reward_btn, (180, 0, 255), "REWARD")
        tip = "MODO SCREENSHOT (opaco) — usa sin --screenshot para overlay transparente"
        cv2.rectangle(out, (0, 0), (out.shape[1], 28), (0, 0, 0), -1)
        cv2.putText(out, tip, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        return out

    cap = ScreenCapture()
    win = "JewelBingo screenshot mode"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    frame = cap.grab()
    vis = paint(frame)
    if fit and vis.shape[1] > 1400:
        sc = 1400 / vis.shape[1]
        vis = cv2.resize(vis, (int(vis.shape[1] * sc), int(vis.shape[0] * sc)))
    cv2.imshow(win, vis)
    if fullscreen:
        try:
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        except Exception:
            pass
    print("Screenshot mode (opaque). Q to close. Prefer default transparent overlay.")
    while True:
        if cv2.waitKey(50) & 0xFF in (ord("q"), ord("Q"), 27):
            break
    cap.close()
    cv2.destroyAllWindows()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Transparent calibration overlay")
    p.add_argument(
        "--cal", type=Path,
        default=ROOT / "assets" / "calibration" / "default.json",
    )
    p.add_argument(
        "--screenshot", action="store_true",
        help="Old opaque screenshot mode (not transparent)",
    )
    p.add_argument("--fit", action="store_true")
    p.add_argument("--windowed", action="store_true")
    args = p.parse_args()

    if not args.cal.exists():
        print(f"No calibration: {args.cal}")
        return 1

    cal = Calibration.load(str(args.cal))
    if args.screenshot:
        return run_screenshot(cal, fit=args.fit, fullscreen=not args.windowed)
    return run_transparent(cal)


if __name__ == "__main__":
    raise SystemExit(main())
