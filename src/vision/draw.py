"""Detect drawn jewel (ROI-first, board-blink as support) and marked cells."""

from __future__ import annotations

from collections import Counter, deque
from typing import Optional

import cv2
import numpy as np

from ..capture import crop
from ..types import BOARD_SIZE, CENTER, JEWEL_TYPES, BoardState, Calibration
from .board import cell_rects
from .templates import JewelClassifier


class DrawDetector:
    """
    During PLAYING, identify the currently drawn jewel.

    Primary: classify calibrated draw_jewel_roi (like friend's portable bot).
    Support: board-cell blink outliers mapped through known board layout.
    """

    def __init__(
        self,
        calibration: Calibration,
        classifier: Optional[JewelClassifier] = None,
        history: int = 12,
        blink_threshold: float = 10.0,
        cell_blink_threshold: float = 10.0,
        margin_ratio: float = 1.25,
    ) -> None:
        self.cal = calibration
        self.classifier = classifier or JewelClassifier(min_score=0.04)
        self.history: deque[np.ndarray] = deque(maxlen=history)
        self.cell_means: deque[np.ndarray] = deque(maxlen=history)
        self.roi_labels: deque[str] = deque(maxlen=8)
        self.blink_threshold = blink_threshold
        self.cell_blink_threshold = cell_blink_threshold
        self.margin_ratio = margin_ratio
        self._cells = cell_rects(calibration.grid)
        self._board: Optional[BoardState] = None
        self._last_conf: float = 0.0
        self._last_source: str = ""

    def reset(self) -> None:
        self.history.clear()
        self.cell_means.clear()
        self.roi_labels.clear()
        self._last_conf = 0.0
        self._last_source = ""

    def set_board(self, board: BoardState) -> None:
        self._board = board

    @property
    def last_confidence(self) -> float:
        return self._last_conf

    @property
    def last_source(self) -> str:
        return self._last_source

    def push(self, frame: np.ndarray) -> None:
        roi = crop(frame, self.cal.draw_jewel_roi)
        if roi.size > 0:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
            self.history.append(gray)
            label = self.classifier.classify_draw_roi(roi)
            if label and label != "FREE" and label in JEWEL_TYPES:
                self.roi_labels.append(label)

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

    def classify_roi_now(self, frame: np.ndarray) -> Optional[str]:
        roi = crop(frame, self.cal.draw_jewel_roi)
        if roi.size == 0:
            return None
        jewel = self.classifier.classify_draw_roi(roi)
        if jewel == "FREE" or jewel not in JEWEL_TYPES:
            return None
        return jewel

    def stable_roi_vote(self, min_votes: int = 3) -> Optional[str]:
        if len(self.roi_labels) < min_votes:
            return None
        recent = list(self.roi_labels)[-min_votes:]
        counts = Counter(recent)
        jewel, n = counts.most_common(1)[0]
        if n >= min_votes and len(set(recent)) == 1:
            self._last_conf = 2.0
            self._last_source = "roi_stable"
            return jewel
        if n >= max(2, min_votes - 1):
            self._last_conf = 1.3
            self._last_source = "roi_majority"
            return jewel
        return None

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
            return None
        if second_v > 0 and best_v < second_v * self.margin_ratio:
            return None
        self._last_conf = best_v / max(second_v, 1.0)
        self._last_source = "board_blink"
        return best_j

    def most_blinking_cell(
        self, board: BoardState, jewel: str
    ) -> Optional[tuple[int, int]]:
        """Among unmarked candidates of `jewel`, return the cell blinking hardest."""
        if len(self.cell_means) < 4:
            return None
        stack = np.stack(list(self.cell_means), axis=0)
        std = stack.std(axis=0)
        best: Optional[tuple[int, int]] = None
        best_v = -1.0
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if board.marked[r][c] or board.cells[r][c] != jewel:
                    continue
                v = float(std[r, c])
                if v > best_v:
                    best_v = v
                    best = (r, c)
        return best

    def detect(self, frame: np.ndarray, board: Optional[BoardState] = None) -> Optional[str]:
        self.push(frame)
        # 1) Stable ROI vote (friend-bot style)
        roi_j = self.stable_roi_vote(min_votes=3)
        board_j = self.detect_from_board_blink(board)
        if roi_j and board_j and roi_j == board_j:
            self._last_conf = 3.0
            self._last_source = "roi+board"
            return roi_j
        if roi_j:
            return roi_j
        if board_j:
            return board_j
        # 2) single-frame ROI if animating
        if self.blink_score() >= self.blink_threshold:
            one = self.classify_roi_now(frame)
            if one:
                self._last_conf = 1.1
                self._last_source = "roi_blink"
                return one
        return None

    def debug_snapshot(self, board: Optional[BoardState] = None) -> str:
        b = board or self._board
        parts = [
            f"roi_blink={self.blink_score():.1f}",
            f"roi_vote={self.stable_roi_vote(2)}",
            f"board={self.detect_from_board_blink(b)}",
            f"src={self._last_source}",
            f"conf={self._last_conf:.2f}",
        ]
        if self.roi_labels:
            parts.append(f"roi_hist={list(self.roi_labels)[-4:]}")
        return " | ".join(parts)


def patch_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Mean abs diff between two BGR patches (resized to match)."""
    if a is None or b is None or a.size == 0 or b.size == 0:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.mean(np.abs(ga - gb)))


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

    def cell_marked_blue(self, frame: np.ndarray, row: int, col: int) -> bool:
        patch = crop(frame, self._cells[row][col])
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(
            hsv,
            np.array([95, 50, 70], dtype=np.uint8),
            np.array([135, 255, 255], dtype=np.uint8),
        )
        ratio = cv2.countNonZero(blue) / float(patch.shape[0] * patch.shape[1] or 1)
        return ratio >= 0.10

    def update_cell_baseline(self, frame: np.ndarray, row: int, col: int) -> None:
        if self._baseline is None:
            self.set_baseline(frame)
            return
        patch = crop(frame, self._cells[row][col])
        self._baseline[row][col] = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
