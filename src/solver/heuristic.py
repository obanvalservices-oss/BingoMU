"""
Heuristic mark priority (max score):

  1) Prefer cells on incomplete CENTER lines that are still completable
     with the draws that remain (optimistic: enough marks left on that line).
  2) If this jewel has no completable center option, pick the cell that is
     closest to finishing ANY line (prefer completable non-center lines).
  3) Never cling to a center line that cannot finish before draws run out
     when another line can still score.
"""

from __future__ import annotations

from typing import Optional

from ..types import (
    BoardState,
    CENTER,
    CENTER_LINE_POINTS,
    NON_CENTER_LINE_POINTS,
    TARGET_SCORE,
)
from .scoring import (
    all_lines,
    center_lines,
    completed_center_line_count,
    line_complete,
    score_board,
)


def unmarked_needed(board: BoardState, line: list[tuple[int, int]]) -> int:
    return sum(1 for r, c in line if not board.marked[r][c])


def on_incomplete_center(board: BoardState, r: int, c: int) -> bool:
    for ln in center_lines():
        if (r, c) in ln and not line_complete(board, ln):
            return True
    return False


def center_candidates(board: BoardState, jewel: str) -> list[tuple[int, int]]:
    return [
        cell
        for cell in board.candidates(jewel)
        if on_incomplete_center(board, *cell)
    ]


def line_feasible_after_mark(
    board: BoardState,
    line: list[tuple[int, int]],
    cell: tuple[int, int],
    draws_after: int,
) -> bool:
    """True if marking cell on this line leaves need <= remaining future draws."""
    if cell not in line or line_complete(board, line):
        return False
    need = unmarked_needed(board, line)
    # This mark fills one hole; future draws must cover the rest.
    return (need - 1) <= max(0, draws_after)


def cell_has_feasible_center(
    board: BoardState, cell: tuple[int, int], draws_after: int
) -> bool:
    return any(
        line_feasible_after_mark(board, ln, cell, draws_after)
        for ln in center_lines()
        if cell in ln
    )


def cell_has_feasible_any(
    board: BoardState, cell: tuple[int, int], draws_after: int
) -> bool:
    return any(
        line_feasible_after_mark(board, ln, cell, draws_after)
        for ln in all_lines()
        if cell in ln
    )


def cell_has_feasible_non_center(
    board: BoardState, cell: tuple[int, int], draws_after: int
) -> bool:
    return any(
        CENTER not in ln and line_feasible_after_mark(board, ln, cell, draws_after)
        for ln in all_lines()
        if cell in ln
    )


def cell_potential(
    board: BoardState,
    r: int,
    c: int,
    draws_remaining_after: int = 13,
) -> float:
    """
    Higher = better for max score given remaining draws.
    Completing / feasible center >> feasible non-center >> mere progress.
    """
    cell = (r, c)
    draws_after = max(0, int(draws_remaining_after))
    b = board.clone()
    b.mark(r, c)
    score_delta = score_board(b) - score_board(board)
    best = 0.0

    for ln in all_lines():
        if cell not in ln or line_complete(board, ln):
            continue
        need = unmarked_needed(board, ln)
        need_after = need - 1
        is_center = CENTER in ln
        completable = need_after <= draws_after
        # Closeness: fewer holes left after this mark = better
        closeness = (5 - need_after) * 200.0

        if need_after == 0:
            # Completes this line immediately
            pts = CENTER_LINE_POINTS if is_center else NON_CENTER_LINE_POINTS
            val = 1_000_000.0 + pts * 10.0 + closeness
        elif completable and is_center:
            val = 500_000.0 + closeness + CENTER_LINE_POINTS
        elif completable and not is_center:
            val = 300_000.0 + closeness + NON_CENTER_LINE_POINTS
        elif is_center:
            # Center progress but NOT finishable — deprioritize vs feasible edges
            val = 20_000.0 + closeness
        else:
            val = 10_000.0 + closeness

        if val > best:
            best = val

    return best + score_delta * 2.0 + score_board(b) * 0.05


def candidate_pool(
    board: BoardState,
    jewel: str,
    draws_remaining_after: int = 13,
) -> list[tuple[int, int]]:
    """
    Build the set of cells to consider, applying remaining-draw gates.
    """
    cands = board.candidates(jewel)
    if not cands:
        return []

    draws_after = max(0, int(draws_remaining_after))
    center_cands = center_candidates(board, jewel)
    feas_center = [
        cell for cell in center_cands
        if cell_has_feasible_center(board, cell, draws_after)
    ]
    if feas_center:
        return feas_center

    feas_non = [
        cell for cell in cands
        if cell_has_feasible_non_center(board, cell, draws_after)
    ]
    if feas_non:
        return feas_non

    feas_any = [
        cell for cell in cands
        if cell_has_feasible_any(board, cell, draws_after)
    ]
    if feas_any:
        return feas_any

    # Nothing finishable: still pick closest-to-a-line among all candidates
    return cands


def choose_heuristic(
    board: BoardState,
    jewel: str,
    draws_remaining_after: int = 13,
) -> tuple[Optional[tuple[int, int]], float, float]:
    """
    Returns (cell, score_proxy, p_ge_1000_proxy).
    """
    pool = candidate_pool(board, jewel, draws_remaining_after)
    if not pool:
        return None, 0.0, 0.0

    best_cell = None
    best_val = float("-inf")
    best_score = 0
    for cell in pool:
        val = cell_potential(board, *cell, draws_remaining_after=draws_remaining_after)
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
