"""Screen / video frame capture."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .types import Rect


class ScreenCapture:
    """Capture desktop regions via mss."""

    def __init__(self) -> None:
        import mss

        self._mss = mss.mss()

    def grab(self, region: Optional[Rect] = None) -> np.ndarray:
        if region is None:
            mon = self._mss.monitors[1]
            shot = self._mss.grab(mon)
        else:
            shot = self._mss.grab(
                {
                    "left": region.x,
                    "top": region.y,
                    "width": region.w,
                    "height": region.h,
                }
            )
        frame = np.array(shot)[:, :, :3]  # BGRA -> BGR drop A
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def close(self) -> None:
        self._mss.close()


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
