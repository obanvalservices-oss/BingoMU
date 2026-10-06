"""Detect drawn jewel primarily via board-cell blink (matching cells flash)."""

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
    Identify the currently drawn jewel.

    PRIMARY: unmarked board cells of the drawn type flash/pulse — measure
    brightness + blue-glow activity per cell and map to jewel codes via the
    known board layout (TEMPLATE). This avoids CR↔C ROI misreads.

    SECONDARY: draw ROI templates, only if the ROI is clearly animating.
    """

    def __init__(
        self,
        calibration: Calibration,
        classifier: Optional[JewelClassifier] = None,
        history: int = 14,
        blink_threshold: float = 8.0,
        cell_blink_threshold: float = 3.5,
        margin_ratio: float = 1.08,
    ) -> None:
        self.cal = calibration
        self.classifier = classifier or JewelClassifier(min_score=0.04)
        self.history: deque[np.ndarray] = deque(maxlen=history)
        self.cell_bright: deque[np.ndarray] = deque(maxlen=history)
        self.cell_blue: deque[np.ndarray] = deque(maxlen=history)
        self.roi_labels: deque[str] = deque(maxlen=8)
        self.blink_threshold = blink_threshold
        self.cell_blink_threshold = cell_blink_threshold
        self.margin_ratio = margin_ratio
        self._cells = cell_rects(calibration.grid)
        self._board: Optional[BoardState] = None
        self._last_conf: float = 0.0
        self._last_source: str = ""
        self._last_scores: dict[str, float] = {}

    def reset(self) -> None:
        self.history.clear()
        self.cell_bright.clear()
        self.cell_blue.clear()
        self.roi_labels.clear()
        self._last_conf = 0.0
        self._last_source = ""
        self._last_scores = {}

    def set_board(self, board: BoardState) -> None:
        self._board = board

    @property
    def last_confidence(self) -> float:
        return self._last_conf

    @property
    def last_source(self) -> str:
        return self._last_source

    def _cell_metrics(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        bright = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
        blue = np.zeros((BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                patch = crop(frame, self._cells[r][c])
                if patch.size == 0:
                    continue
                gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
                bright[r, c] = float(gray.mean())
                hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
                # highlight / glow (cyan-blue) often used when a cell is selectable
                mask = cv2.inRange(
                    hsv,
                    np.array([85, 40, 80], dtype=np.uint8),
                    np.array([140, 255, 255], dtype=np.uint8),
                )
                # also bright yellow-white flash
                bright_mask = cv2.inRange(
                    hsv,
                    np.array([0, 0, 180], dtype=np.uint8),
                    np.array([179, 80, 255], dtype=np.uint8),
                )
                total = float(patch.shape[0] * patch.shape[1] or 1)
                blue[r, c] = (
                    cv2.countNonZero(mask) + 0.5 * cv2.countNonZero(bright_mask)
                ) / total
        return bright, blue

    def push(self, frame: np.ndarray) -> None:
        roi = crop(frame, self.cal.draw_jewel_roi)
        if roi.size > 0:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
            self.history.append(gray)
            label = self.classifier.classify_draw_roi(roi)
            if label and label != "FREE" and label in JEWEL_TYPES:
                self.roi_labels.append(label)

        bright, blue = self._cell_metrics(frame)
        self.cell_bright.append(bright)
        self.cell_blue.append(blue)

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
            return jewel
        if n >= max(2, min_votes - 1):
            return jewel
        return None

    def _activity_map(self) -> Optional[np.ndarray]:
        """Per-cell activity = brightness range + blue-glow range over recent frames."""
        if len(self.cell_bright) < 5:
            return None
        bstack = np.stack(list(self.cell_bright), axis=0)
        blstack = np.stack(list(self.cell_blue), axis=0)
        bright_range = bstack.max(axis=0) - bstack.min(axis=0)
        blue_range = blstack.max(axis=0) - blstack.min(axis=0)
        # Prefer CHANGE over static blue peak (static peak inflated grey H cells)
        return bright_range * 1.0 + 55.0 * blue_range

    def _jewel_blink_scores(self, board: BoardState) -> dict[str, float]:
        act = self._activity_map()
        scores: dict[str, float] = {j: 0.0 for j in JEWEL_TYPES}
        if act is None:
            return scores
        # For each jewel type, use top-2 cell activities (several cells flash together)
        for j in JEWEL_TYPES:
            vals = []
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if board.marked[r][c]:
                        continue
                    if board.cells[r][c] != j:
                        continue
                    vals.append(float(act[r, c]))
            if not vals:
                continue
            vals.sort(reverse=True)
            scores[j] = vals[0] + (0.5 * vals[1] if len(vals) > 1 else 0.0)
        return scores

    def detect_from_board_blink(self, board: Optional[BoardState] = None) -> Optional[str]:
        b = board or self._board
        if b is None or len(self.cell_bright) < 5:
            return None
        scores = self._jewel_blink_scores(b)
        self._last_scores = dict(scores)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_j, best_v = ranked[0]
        second_v = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_v < self.cell_blink_threshold:
            return None
        gap = best_v - second_v
        # Soft margin: C vs H often close when Chaos is flashing
        ok = (
            second_v <= 0
            or best_v >= second_v * self.margin_ratio
            or gap >= 0.8
            or (best_v >= 9.0 and gap >= 0.25)
        )
        if not ok:
            return None
        self._last_conf = best_v / max(second_v, 0.5)
        self._last_source = "board_blink"
        return best_j

    def most_blinking_cell(
        self, board: BoardState, jewel: str
    ) -> Optional[tuple[int, int]]:
        act = self._activity_map()
        if act is None:
            return None
        best: Optional[tuple[int, int]] = None
        best_v = -1.0
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if board.marked[r][c] or board.cells[r][c] != jewel:
                    continue
                v = float(act[r, c])
                if v > best_v:
                    best_v = v
                    best = (r, c)
        return best

    def detect(self, frame: np.ndarray, board: Optional[BoardState] = None) -> Optional[str]:
        self.push(frame)
        board_j = self.detect_from_board_blink(board)
        if board_j:
            return board_j

        # ROI is unreliable (CR vs C confusion) — only use if strongly animating
        blink = self.blink_score()
        roi_j = self.stable_roi_vote(min_votes=4)
        if roi_j and blink >= 5.0:
            # Disambiguate Chaos vs Creation using board activity if close
            scores = self._last_scores
            if roi_j in ("C", "CR") and scores:
                c_sc = scores.get("C", 0.0)
                cr_sc = scores.get("CR", 0.0)
                if c_sc > cr_sc * 1.1 and c_sc >= self.cell_blink_threshold * 0.7:
                    self._last_source = "roi+board_C"
                    self._last_conf = 1.5
                    return "C"
                if cr_sc > c_sc * 1.1 and cr_sc >= self.cell_blink_threshold * 0.7:
                    self._last_source = "roi+board_CR"
                    self._last_conf = 1.5
                    return "CR"
            self._last_source = "roi_blink"
            self._last_conf = blink / 5.0
            return roi_j
        return None

    def debug_snapshot(self, board: Optional[BoardState] = None) -> str:
        b = board or self._board
        board_j = self.detect_from_board_blink(b)
        scores = self._last_scores or (self._jewel_blink_scores(b) if b else {})
        tip = ", ".join(
            f"{j}={scores.get(j, 0):.1f}"
            for j, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:4]
        )
        return (
            f"roi_blink={self.blink_score():.1f} | roi_vote={self.stable_roi_vote(3)} | "
            f"board={board_j} | src={self._last_source} | conf={self._last_conf:.2f} | "
            f"board_scores=[{tip}]"
        )


def patch_delta(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.size == 0 or b.size == 0:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.mean(np.abs(ga - gb)))


class MarkedCellDetector:
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
                if self.cell_marked_blue(frame, r, c):
                    marked[r][c] = True
                    continue
                if self._baseline is None:
                    continue
                patch = crop(frame, self._cells[r][c])
                gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
                base = self._baseline[r][c]
                if gray.shape != base.shape:
                    gray = cv2.resize(gray, (base.shape[1], base.shape[0]))
                marked[r][c] = float(np.mean(np.abs(gray - base))) >= self.diff_threshold
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
