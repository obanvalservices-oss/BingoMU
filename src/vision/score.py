"""OCR Total Score from calibrated score ROI."""

from __future__ import annotations

import re
from typing import Optional

import cv2
import numpy as np

from ..capture import crop
from ..types import Rect


def _preprocess_for_ocr(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Upscale for small UI text
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Prefer white text on dark: invert if mostly white
    if np.mean(th) > 127:
        th = 255 - th
    return th


def read_total_score(frame: np.ndarray, score_roi: Rect) -> Optional[int]:
    """
    Try pytesseract OCR; fall back to digit contour heuristic returning None on failure.
    """
    roi = crop(frame, score_roi)
    if roi.size == 0:
        return None
    proc = _preprocess_for_ocr(roi)

    text = ""
    try:
        import pytesseract

        text = pytesseract.image_to_string(
            proc,
            config="--psm 7 -c tessedit_char_whitelist=0123456789",
        )
    except Exception:
        text = ""

    nums = re.findall(r"\d{2,5}", text.replace(" ", ""))
    if nums:
        # Prefer the largest number in ROI (total score tends to dominate)
        return max(int(n) for n in nums)

    # Fallback: estimate via bright digit blobs — return None if unreliable
    return None


def read_remaining_draws(frame: np.ndarray, score_roi: Rect) -> Optional[int]:
    """
    Try to read remaining draws (0–14) from the calibrated score/counter ROI.
    Prefers a small integer; ignores large totals (score).
    """
    roi = crop(frame, score_roi)
    if roi.size == 0:
        return None
    proc = _preprocess_for_ocr(roi)
    text = ""
    try:
        import pytesseract

        text = pytesseract.image_to_string(
            proc,
            config="--psm 7 -c tessedit_char_whitelist=0123456789",
        )
    except Exception:
        text = ""
    nums = [int(n) for n in re.findall(r"\d{1,2}", text.replace(" ", ""))]
    small = [n for n in nums if 0 <= n <= 14]
    if small:
        return min(small)
    return None
