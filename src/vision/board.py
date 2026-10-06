"""Read 5x5 Jewel Bingo board from a calibrated grid ROI."""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..capture import crop
from ..types import BOARD_SIZE, CENTER, BoardState, Calibration, Rect
from .templates import JewelClassifier


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


class BoardReader:
    def __init__(self, calibration: Calibration, classifier: Optional[JewelClassifier] = None) -> None:
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

    def cell_image(self, frame: np.ndarray, row: int, col: int) -> np.ndarray:
        return crop(frame, self._cells[row][col])
