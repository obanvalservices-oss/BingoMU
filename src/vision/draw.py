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

    Strategy:
      1) ROI classify when the draw icon is blinking / changing.
      2) Board blink: unmarked cells with outlier temporal variance → jewel type
         (require clear margin vs 2nd place to avoid noise clicks).
    """

    def __init__(
        self,
        calibration: Calibration,
        classifier: Optional[JewelClassifier] = None,
        history: int = 12,
        blink_threshold: float = 12.0,
        cell_blink_threshold: float = 12.0,
        margin_ratio: float = 1.35,
    ) -> None:
        self.cal = calibration
        self.classifier = classifier or JewelClassifier(min_score=0.05)
        self.history: deque[np.ndarray] = deque(maxlen=history)
        self.cell_means: deque[np.ndarray] = deque(maxlen=history)
        self.blink_threshold = blink_threshold
        self.cell_blink_threshold = cell_blink_threshold
        self.margin_ratio = margin_ratio
        self._cells = cell_rects(calibration.grid)
        self._board: Optional[BoardState] = None
        self._last_conf: float = 0.0

    def reset(self) -> None:
        self.history.clear()
        self.cell_means.clear()
        self._last_conf = 0.0

    def set_board(self, board: BoardState) -> None:
        self._board = board

    @property
    def last_confidence(self) -> float:
        return self._last_conf

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

    def _jewel_blink_scores(self, board: BoardState) -> dict[str, float]:
        stack = np.stack(list(self.cell_means), axis=0)
        std = stack.std(axis=0)
        scores: dict[str, float] = {j: 0.0 for j in JEWEL_TYPES}
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if board.marked[r][c]:
                    continue
                jewel = board.cells[r][c]
                if jewel not in scores:
                    continue
                # average of top blinks for this jewel type (more stable than max alone)
                scores[jewel] = max(scores[jewel], float(std[r, c]))
        return scores

    def detect_from_board_blink(self, board: Optional[BoardState] = None) -> Optional[str]:
        b = board or self._board
        if b is None or len(self.cell_means) < 5:
            return None
        scores = self._jewel_blink_scores(b)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_j, best_v = ranked[0]
        second_v = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_v < self.cell_blink_threshold:
            self._last_conf = 0.0
            return None
        # Require clear winner so we don't click on ambient GRD noise
        if second_v > 0 and best_v < second_v * self.margin_ratio:
            self._last_conf = 0.0
            return None
        self._last_conf = best_v / max(second_v, 1.0)
        return best_j

    def detect_from_roi(self, frame: np.ndarray) -> Optional[str]:
        roi = crop(frame, self.cal.draw_jewel_roi)
        if roi.size == 0:
            return None
        # Prefer ROI only when it is actually animating
        if self.blink_score() < self.blink_threshold and len(self.history) >= 4:
            return None
        jewel = self.classifier.classify_draw_roi(roi)
        if jewel == "FREE" or jewel is None:
            return None
        self._last_conf = max(self._last_conf, self.blink_score() / 10.0)
        return jewel

    def detect(self, frame: np.ndarray, board: Optional[BoardState] = None) -> Optional[str]:
        self.push(frame)
        # ROI first when clearly blinking (often the drawn icon itself)
        roi_j = self.detect_from_roi(frame)
        board_j = self.detect_from_board_blink(board)
        if roi_j and board_j and roi_j == board_j:
            self._last_conf = max(self._last_conf, 2.0)
            return roi_j
        if board_j and self._last_conf >= 1.35:
            return board_j
        if roi_j and self.blink_score() >= self.blink_threshold:
            return roi_j
        return board_j or roi_j

    def debug_snapshot(self, board: Optional[BoardState] = None) -> str:
        b = board or self._board
        roi_blink = self.blink_score()
        board_j = self.detect_from_board_blink(b)
        parts = [
            f"roi_blink={roi_blink:.1f}",
            f"board_guess={board_j}",
            f"conf={self._last_conf:.2f}",
        ]
        if len(self.cell_means) >= 4 and b is not None:
            scores = self._jewel_blink_scores(b)
            tip = ", ".join(
                f"{j}={scores[j]:.1f}"
                for j, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
            )
            parts.append(f"scores=[{tip}]")
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
