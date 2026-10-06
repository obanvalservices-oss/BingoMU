"""Read 5x5 Jewel Bingo board from a calibrated grid ROI."""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..capture import crop
from ..types import BOARD_SIZE, CENTER, JEWEL_TYPES, BoardState, Calibration, Rect
from .templates import JewelClassifier, dominant_jewel_score


def cell_rects(grid: Rect) -> list[list[Rect]]:
    """Split grid ROI into 5x5 cell rectangles (absolute coords)."""
    cells: list[list[Rect]] = []
    cw = grid.w / BOARD_SIZE
    ch = grid.h / BOARD_SIZE
    for r in range(BOARD_SIZE):
        row: list[Rect] = []
        for c in range(BOARD_SIZE):
            x = int(grid.x + c * cw)
            y = int(grid.y + r * ch)
            w = int((grid.x + (c + 1) * cw) - x)
            h = int((grid.y + (r + 1) * ch) - y)
            row.append(Rect(x, y, w, h))
        cells.append(row)
    return cells


def _empty_score_grid() -> list[list[dict[str, float]]]:
    return [[{j: 0.0 for j in JEWEL_TYPES} for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


def assign_four_each(score_grid: list[list[dict[str, float]]]) -> BoardState:
    """
    Force a legal MU board: exactly 4 of each jewel + FREE center.
    Greedy: repeatedly pick highest (cell, jewel) with jewel count < 4.
    """
    board = BoardState()
    assigned: set[tuple[int, int]] = {CENTER}
    counts = {j: 0 for j in JEWEL_TYPES}
    pairs: list[tuple[float, int, int, str]] = []
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if (r, c) == CENTER:
                continue
            for j in JEWEL_TYPES:
                pairs.append((float(score_grid[r][c].get(j, 0.0)), r, c, j))
    pairs.sort(reverse=True)
    for sc, r, c, j in pairs:
        if (r, c) in assigned:
            continue
        if counts[j] >= 4:
            continue
        if sc <= 0.0 and counts[j] < 4:
            # Still allow very weak fills only after strong ones taken
            pass
        board.cells[r][c] = j
        assigned.add((r, c))
        counts[j] += 1
        if len(assigned) >= BOARD_SIZE * BOARD_SIZE:
            break
    # Fill any leftover cells with under-used jewels
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if (r, c) == CENTER or board.cells[r][c] is not None:
                continue
            for j in JEWEL_TYPES:
                if counts[j] < 4:
                    board.cells[r][c] = j
                    counts[j] += 1
                    break
    return board


class BoardReader:
    def __init__(
        self, calibration: Calibration, classifier: Optional[JewelClassifier] = None
    ) -> None:
        self.cal = calibration
        self.classifier = classifier or JewelClassifier()
        self._cells = cell_rects(calibration.grid)

    def read(self, frame: np.ndarray) -> BoardState:
        board = BoardState()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if (r, c) == CENTER:
                    board.cells[r][c] = "FREE"
                    board.marked[r][c] = True
                    continue
                rect = self._cells[r][c]
                patch = crop(frame, rect)
                label = self.classifier.classify(patch, allow_free=False)
                board.cells[r][c] = label
        return board

    def cell_scores(self, frame: np.ndarray, r: int, c: int) -> dict[str, float]:
        """Per-jewel confidence for one cell (template + color blend)."""
        patch = crop(frame, self._cells[r][c])
        scores = {j: 0.0 for j in JEWEL_TYPES}
        if patch.size == 0:
            return scores
        # Color ratios
        color = dominant_jewel_score(patch, self.classifier.profiles)
        for j in JEWEL_TYPES:
            scores[j] += 0.45 * float(color.get(j, 0.0))
        # Template scores
        if self.classifier.template_feats:
            for j in JEWEL_TYPES:
                _, sc, _ = self.classifier._score_one(patch, j)
                scores[j] += 0.55 * max(0.0, float(sc))
        return scores

    def score_grid(self, frame: np.ndarray) -> list[list[dict[str, float]]]:
        grid = _empty_score_grid()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if (r, c) == CENTER:
                    continue
                grid[r][c] = self.cell_scores(frame, r, c)
        return grid

    def read_auto(self, frames: list[np.ndarray]) -> tuple[BoardState, int]:
        """
        Robust AUTO board read: average scores across frames, then assign
        exactly 4 of each jewel. Returns (board, known_before_assign).
        """
        if not frames:
            return BoardState(), 0
        acc = _empty_score_grid()
        n = 0
        for frame in frames:
            g = self.score_grid(frame)
            n += 1
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if (r, c) == CENTER:
                        continue
                    for j in JEWEL_TYPES:
                        acc[r][c][j] += g[r][c][j]
        if n > 1:
            for r in range(BOARD_SIZE):
                for c in range(BOARD_SIZE):
                    if (r, c) == CENTER:
                        continue
                    for j in JEWEL_TYPES:
                        acc[r][c][j] /= float(n)

        # How many cells would a soft classify fill?
        known = 0
        soft = BoardState()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if (r, c) == CENTER:
                    continue
                ranked = sorted(acc[r][c].items(), key=lambda kv: kv[1], reverse=True)
                best_j, best_s = ranked[0]
                second = ranked[1][1] if len(ranked) > 1 else 0.0
                if best_s >= 0.22 and (best_s - second) >= 0.03:
                    soft.cells[r][c] = best_j
                    known += 1

        board = assign_four_each(acc)
        return board, known

    def labeled_count(self, board: BoardState) -> int:
        n = 0
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if (r, c) == CENTER:
                    continue
                if board.cells[r][c] in JEWEL_TYPES:
                    n += 1
        return n

    def cell_image(self, frame: np.ndarray, row: int, col: int) -> np.ndarray:
        return crop(frame, self._cells[row][col])
