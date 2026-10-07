"""Screen / video frame capture (memory-conscious)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .types import Calibration, Rect


def vision_grab_rect(cal: Calibration, pad: int = 80) -> Rect:
    """Tight screen rect covering every calibrated ROI (+ pad)."""
    rects = [
        cal.overlay,
        cal.grid,
        cal.boxes,
        cal.auto_btn,
        cal.start_btn,
        cal.reward_btn,
        cal.score_roi,
        cal.draw_jewel_roi,
        *cal.jewel_btns.values(),
    ]
    x0 = min(r.x for r in rects) - pad
    y0 = min(r.y for r in rects) - pad
    x1 = max(r.x + r.w for r in rects) + pad
    y1 = max(r.y + r.h for r in rects) + pad
    return Rect(max(0, x0), max(0, y0), max(1, x1 - max(0, x0)), max(1, y1 - max(0, y0)))


def shift_calibration(cal: Calibration, ox: int, oy: int) -> Calibration:
    """Translate all ROIs so (0,0) is the grab origin (absolute clicks stay on original cal)."""

    def sh(r: Rect) -> Rect:
        return Rect(r.x - ox, r.y - oy, r.w, r.h)

    return Calibration(
        overlay=sh(cal.overlay),
        grid=sh(cal.grid),
        boxes=sh(cal.boxes),
        auto_btn=sh(cal.auto_btn),
        start_btn=sh(cal.start_btn),
        reward_btn=sh(cal.reward_btn),
        score_roi=sh(cal.score_roi),
        draw_jewel_roi=sh(cal.draw_jewel_roi),
        jewel_btns={k: sh(v) for k, v in (cal.jewel_btns or {}).items()},
        window_title=cal.window_title,
        click_delay_s=cal.click_delay_s,
        draw_timeout_s=cal.draw_timeout_s,
        post_auto_wait_s=cal.post_auto_wait_s,
        place_delay_s=cal.place_delay_s,
    )


class ScreenCapture:
    """Capture desktop regions via mss. Prefer a tight `region` to cut RAM."""

    def __init__(self, region: Optional[Rect] = None) -> None:
        import mss

        self._mss = mss.mss()
        self.region = region

    def grab(self, region: Optional[Rect] = None) -> np.ndarray:
        use = region or self.region
        if use is None:
            mon = self._mss.monitors[1]
            shot = self._mss.grab(mon)
        else:
            # Clamp to virtual screen so mss never gets invalid rects
            mon0 = self._mss.monitors[0]
            left = max(mon0["left"], use.x)
            top = max(mon0["top"], use.y)
            right = min(mon0["left"] + mon0["width"], use.x + use.w)
            bottom = min(mon0["top"] + mon0["height"], use.y + use.h)
            shot = self._mss.grab(
                {
                    "left": int(left),
                    "top": int(top),
                    "width": max(1, int(right - left)),
                    "height": max(1, int(bottom - top)),
                }
            )
        # Explicit copy — mss reuses its internal buffer
        bgra = np.array(shot, dtype=np.uint8, copy=True)
        if bgra.ndim == 3 and bgra.shape[2] == 4:
            frame = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        else:
            frame = np.ascontiguousarray(bgra[:, :, :3])
        del bgra
        return frame

    def close(self) -> None:
        try:
            self._mss.close()
        except Exception:
            pass


class VideoCapture:
    """Frame source for offline replay / vision validation."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.cap = cv2.VideoCapture(self.path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {self.path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self.cap.read()
        return frame if ok else None

    def seek_ms(self, ms: float) -> Optional[np.ndarray]:
        self.cap.set(cv2.CAP_PROP_POS_MSEC, ms)
        return self.read()

    def seek_frame(self, idx: int) -> Optional[np.ndarray]:
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        return self.read()

    def iter_frames(self, step: int = 1):
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        i = 0
        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            if i % step == 0:
                yield i, frame
            i += 1

    def close(self) -> None:
        self.cap.release()


def crop(frame: np.ndarray, rect: Rect) -> np.ndarray:
    return frame[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w].copy()
