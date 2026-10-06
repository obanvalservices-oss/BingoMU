"""Detect drawn (blinking) jewel and newly marked cells."""

from __future__ import annotations

from collections import deque
from typing import Optional

import cv2
import numpy as np

from ..capture import crop
from ..types import BOARD_SIZE, CENTER, JEWEL_TYPES, BoardState, Calibration
from .board import cell_rects
from .templates import JewelClassifier


class DrawDetector:
    """
    Detect which jewel is currently drawn.

    Primary (when board layout is known): cells of the drawn type blink on the
    5x5 grid — measure temporal variance per cell and map back to jewel codes.

    Secondary: classify the calibrated draw_jewel_roi by color/template.
    """

    def __init__(
        self,
        calibration: Calibration,
        classifier: Optional[JewelClassifier] = None,
        history: int = 10,
        blink_threshold: float = 10.0,
        cell_blink_threshold: float = 8.0,
    ) -> None:
        self.cal = calibration
        self.classifier = classifier or JewelClassifier(min_score=0.05)
        self.history: deque[np.ndarray] = deque(maxlen=history)
        self.cell_means: deque[np.ndarray] = deque(maxlen=history)
        self.blink_threshold = blink_threshold
        self.cell_blink_threshold = cell_blink_threshold
        self._cells = cell_rects(calibration.grid)
        self._board: Optional[BoardState] = None

    def reset(self) -> None:
        self.history.clear()
        self.cell_means.clear()

    def set_board(self, board: BoardState) -> None:
        self._board = board

    def push(self, frame: np.ndarray) -> None:
        roi = crop(frame, self.cal.draw_jewel_roi)
        if roi.size > 0:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
            self.history.append(gray)

        means = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                patch = crop(frame, self._cells[r][c])
                if patch.size == 0:
                    continue
                means[r, c] = float(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).mean())
        self.cell_means.append(means)

    def blink_score(self) -> float:
        if len(self.history) < 3:
            return 0.0
        stack = np.stack(list(self.history), axis=0)
        return float(stack.std(axis=0).mean())

    def detect_from_board_blink(self, board: Optional[BoardState] = None) -> Optional[str]:
        """Infer drawn jewel from which unmarked board cells are blinking."""
        b = board or self._board
        if b is None or len(self.cell_means) < 4:
            return None
        stack = np.stack(list(self.cell_means), axis=0)  # T,5,5
        std = stack.std(axis=0)

        scores: dict[str, list[float]] = {j: [] for j in JEWEL_TYPES}
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if b.marked[r][c]:
                    continue
                jewel = b.cells[r][c]
                if jewel not in scores:
                    continue
                scores[jewel].append(float(std[r, c]))

        best_j: Optional[str] = None
        best_v = 0.0
        for j, vals in scores.items():
            if not vals:
                continue
            v = max(vals)
            if v > best_v:
                best_v = v
                best_j = j

        if best_j is None or best_v < self.cell_blink_threshold:
            return None
        return best_j

    def detect_from_roi(self, frame: np.ndarray) -> Optional[str]:
        roi = crop(frame, self.cal.draw_jewel_roi)
        if roi.size == 0:
            return None
        jewel = self.classifier.classify_draw_roi(roi)
        if jewel == "FREE" or jewel is None:
            return None
        return jewel

    def detect(self, frame: np.ndarray, board: Optional[BoardState] = None) -> Optional[str]:
        self.push(frame)
        j = self.detect_from_board_blink(board)
        if j:
            return j
        return self.detect_from_roi(frame)

    def debug_snapshot(self, board: Optional[BoardState] = None) -> str:
        b = board or self._board
        roi_blink = self.blink_score()
        board_j = self.detect_from_board_blink(b)
        parts = [f"roi_blink={roi_blink:.1f}", f"board_guess={board_j}"]
        if len(self.cell_means) >= 4 and b is not None:
            stack = np.stack(list(self.cell_means), axis=0)
            std = stack.std(axis=0)
            top = []
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if b.marked[r][c]:
                        continue
                    top.append((float(std[r, c]), r, c, b.cells[r][c]))
            top.sort(reverse=True)
            tip = ", ".join(f"R{r+1}C{c+1}:{j}={v:.1f}" for v, r, c, j in top[:3])
            parts.append(f"top=[{tip}]")
        return " | ".join(parts)


class MarkedCellDetector:
    """Track which board cells become marked after clicks via frame differencing."""

    def __init__(self, calibration: Calibration, diff_threshold: float = 25.0) -> None:
        self.cal = calibration
        self.diff_threshold = diff_threshold
        self._cells = cell_rects(calibration.grid)
        self._baseline: Optional[list[list[np.ndarray]]] = None

    def set_baseline(self, frame: np.ndarray) -> None:
        self._baseline = []
        for r in range(BOARD_SIZE):
            row = []
            for c in range(BOARD_SIZE):
                patch = crop(frame, self._cells[r][c])
                row.append(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32))
            self._baseline.append(row)

    def detect_marked(self, frame: np.ndarray) -> list[list[bool]]:
        marked = [[False] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        marked[CENTER[0]][CENTER[1]] = True
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if (r, c) == CENTER:
                    continue
                patch = crop(frame, self._cells[r][c])
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                blue = cv2.inRange(
                    hsv,
                    np.array([95, 60, 80], dtype=np.uint8),
                    np.array([130, 255, 255], dtype=np.uint8),
                )
                ratio = cv2.countNonZero(blue) / float(patch.shape[0] * patch.shape[1] or 1)
                if ratio >= 0.12:
                    marked[r][c] = True
                    continue
                if self._baseline is None:
                    continue
                gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
                base = self._baseline[r][c]
                if gray.shape != base.shape:
                    gray = cv2.resize(gray, (base.shape[1], base.shape[0]))
                diff = float(np.mean(np.abs(gray - base)))
                marked[r][c] = diff >= self.diff_threshold
        return marked

    def update_cell_baseline(self, frame: np.ndarray, row: int, col: int) -> None:
        if self._baseline is None:
            self.set_baseline(frame)
            return
        patch = crop(frame, self._cells[row][col])
        self._baseline[row][col] = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
