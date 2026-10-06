"""Heuristic: ALWAYS prefer lines through FREE center (saves draws)."""

from __future__ import annotations

from typing import Optional

from ..types import BoardState, TARGET_SCORE, CENTER
from .scoring import (
    center_lines,
    all_lines,
    line_complete,
    score_board,
    completed_center_line_count,
    line_progress,
)


def on_incomplete_center(board: BoardState, r: int, c: int) -> bool:
    for ln in center_lines():
        if (r, c) in ln and not line_complete(board, ln):
            return True
    return False


def center_candidates(
    board: BoardState, jewel: str
) -> list[tuple[int, int]]:
    """Candidates that sit on an incomplete center line (FREE already helps)."""
    return [
        cell
        for cell in board.candidates(jewel)
        if on_incomplete_center(board, *cell)
    ]


def _center_progress_score(board: BoardState, r: int, c: int) -> float:
    """Higher = closer to finishing a center line."""
    total = 0.0
    for ln in center_lines():
        if (r, c) not in ln or line_complete(board, ln):
            continue
        marked, _ = line_progress(board, ln)
        after = marked + 1
        if after >= 5:
            total += 5000.0  # completes center line now
        elif after == 4:
            total += 800.0
        elif after == 3:
            total += 350.0
        else:
            total += 120.0 * after
        total += 50.0  # on a center line
    return total


def _non_center_score(board: BoardState, r: int, c: int) -> float:
    """Fallback when this jewel has no cell on an incomplete center line."""
    total = 0.0
    b = board.clone()
    b.mark(r, c)
    for ln in all_lines():
        if (r, c) not in ln or CENTER in ln:
            continue
        if line_complete(b, ln):
            total += 400.0
        else:
            marked, _ = line_progress(b, ln)
            total += marked * 40.0
    total += score_board(b) * 0.2
    return total


def cell_potential(board: BoardState, r: int, c: int) -> float:
    """
    Priority:
      1) Any cell on incomplete center line beats all non-center cells
      2) Among center: prefer completing / near-complete center lines
      3) Else: best non-center line progress
    """
    b = board.clone()
    b.mark(r, c)
    if on_incomplete_center(board, r, c):
        return 100_000.0 + _center_progress_score(board, r, c) + score_board(b) * 0.05
    return _non_center_score(board, r, c)


def choose_heuristic(
    board: BoardState, jewel: str
) -> tuple[Optional[tuple[int, int]], float, float]:
    """
    Returns (cell, expected_score_proxy, p_ge_1000_proxy).

    If any candidate lies on an incomplete center line, ONLY those are considered.
    """
    cands = board.candidates(jewel)
    if not cands:
        return None, 0.0, 0.0

    pool = center_candidates(board, jewel) or cands

    best_cell = None
    best_val = float("-inf")
    best_score = 0
    for cell in pool:
        val = cell_potential(board, *cell)
        if val > best_val:
            best_val = val
            best_cell = cell
            bb = board.clone()
            bb.mark(*cell)
            best_score = score_board(bb)

    p = 1.0 if best_score >= TARGET_SCORE else min(0.95, best_score / TARGET_SCORE)
    if best_cell is not None:
        bb = board.clone()
        bb.mark(*best_cell)
        if completed_center_line_count(bb) > completed_center_line_count(board):
            p = min(1.0, p + 0.15)
    return best_cell, float(best_score), float(p)
