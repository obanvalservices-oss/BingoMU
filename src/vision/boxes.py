"""Locate the blue (always-pick) chest among the reward boxes."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from ..capture import crop
from ..types import Calibration, Rect


def find_blue_chest_center(
    frame: np.ndarray,
    cal: Calibration,
    search: Optional[Rect] = None,
) -> Optional[tuple[int, int]]:
    """
    Find the leftmost blue chest in a search band above the board.
    Falls back to calibrated boxes.center if vision fails.
    """
    if search is None:
        # Band covering the box row: left of grid / top of overlay
        o = cal.overlay
        g = cal.grid
        x = max(0, min(o.x, g.x) - 10)
        y = max(0, min(o.y, g.y) - 10)
        # from overlay top down to just above grid
        bottom = max(g.y - 5, y + 40)
        w = max(cal.boxes.w * 8, g.w + 80)
        h = max(40, bottom - y)
        # Prefer a wider band around calibrated boxes
        bx = cal.boxes
        x = max(0, min(x, bx.x - 80))
        y = max(0, min(y, bx.y - 30))
        w = max(w, bx.w + 320)
        h = max(h, bx.h + 80)
        search = Rect(x, y, w, h)

    roi = crop(frame, search)
    if roi.size == 0:
        return cal.boxes.center

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # MU blue chest glow / lid
    blue = cv2.inRange(
        hsv,
        np.array([95, 70, 70], dtype=np.uint8),
        np.array([130, 255, 255], dtype=np.uint8),
    )
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, int, int]] = []  # (x_abs, y_abs, area)
    for c in cnts:
        area = int(cv2.contourArea(c))
        if area < 80 or area > 8000:
            continue
        x, y, w, h = cv2.boundingRect(c)
        cx = search.x + x + w // 2
        cy = search.y + y + h // 2
        candidates.append((cx, cy, area))

    if not candidates:
        return cal.boxes.center

    # Leftmost blue blob (top-left / blue chest)
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][0], candidates[0][1]
