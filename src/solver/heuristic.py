"""Heuristic cell chooser favoring center-crossing lines toward 1000+."""

from __future__ import annotations

from typing import Optional

from ..types import BoardState, TARGET_SCORE
from .scoring import (
    center_lines,
    all_lines,
    line_complete,
    score_board,
    completed_center_line_count,
)


def _potential(board: BoardState, r: int, c: int) -> float:
    """Higher is better: prefer moves that advance center lines, then any line."""
    b = board.clone()
    b.mark(r, c)
    score_now = score_board(b)
    center_done = completed_center_line_count(b)

    # Immediate line completions (weighted)
    immediate = 0.0
    for ln in all_lines():
        if (r, c) not in ln:
            continue
        if line_complete(b, ln):
            immediate += 400.0 if (2, 2) in ln else 250.0

    # Progress on incomplete center lines containing this cell
    progress = 0.0
    for ln in center_lines():
        if (r, c) not in ln:
            continue
        marked = sum(1 for rr, cc in ln if b.marked[rr][cc])
        progress += marked * 35.0
        # Bonus when one away from completing a center line
        if marked == 4:
            progress += 120.0

    # Mild preference for cells that appear in more lines (hubs)
    hub = sum(1 for ln in all_lines() if (r, c) in ln) * 8.0

    # Soft push toward target — strongly prefer moves that complete center lines
    target_boost = 0.0
    if score_now >= TARGET_SCORE:
        target_boost = 800.0
    else:
        target_boost = score_now * 0.35
        # Extra weight when this move completes any center line
        for ln in center_lines():
            if (r, c) in ln and line_complete(b, ln):
                target_boost += 350.0
        # Near-miss: if under 1000, heavily prefer completing ANY new line
        if score_now < TARGET_SCORE:
            for ln in all_lines():
                if (r, c) in ln and line_complete(b, ln):
                    target_boost += 200.0
            if score_now >= 900:
                target_boost += (TARGET_SCORE - score_now) * 2.0

    return score_now + immediate + progress + hub + target_boost + center_done * 80.0


def choose_heuristic(
    board: BoardState, jewel: str
) -> tuple[Optional[tuple[int, int]], float, float]:
    """
    Returns (cell, expected_score_proxy, p_ge_1000_proxy).
    p_ge_1000_proxy is a soft 0/1 from whether scoring the best move already clears 1000
    or is within striking distance given remaining theoretical max — here simplified.
    """
    cands = board.candidates(jewel)
    if not cands:
        return None, 0.0, 0.0

    best_cell = None
    best_val = float("-inf")
    best_score = 0
    for cell in cands:
        val = _potential(board, *cell)
        if val > best_val:
            best_val = val
            best_cell = cell
            bb = board.clone()
            bb.mark(*cell)
            best_score = score_board(bb)

    p = 1.0 if best_score >= TARGET_SCORE else min(0.95, best_score / TARGET_SCORE)
    return best_cell, float(best_score), float(p)
