"""Bingo line definitions and score calculation."""

from __future__ import annotations

from ..types import (
    BOARD_SIZE,
    CENTER,
    CENTER_LINE_POINTS,
    MARKED_CELL_POINTS,
    NON_CENTER_LINE_POINTS,
    BoardState,
)


def all_lines() -> list[list[tuple[int, int]]]:
    lines: list[list[tuple[int, int]]] = []
    for r in range(BOARD_SIZE):
        lines.append([(r, c) for c in range(BOARD_SIZE)])
    for c in range(BOARD_SIZE):
        lines.append([(r, c) for r in range(BOARD_SIZE)])
    lines.append([(i, i) for i in range(BOARD_SIZE)])
    lines.append([(i, BOARD_SIZE - 1 - i) for i in range(BOARD_SIZE)])
    return lines


def center_lines() -> list[list[tuple[int, int]]]:
    cr, cc = CENTER
    return [ln for ln in all_lines() if (cr, cc) in ln]


def line_complete(board: BoardState, line: list[tuple[int, int]]) -> bool:
    return all(board.marked[r][c] for r, c in line)


def score_board(board: BoardState) -> int:
    """
    Apply scoring rules:
    - 312 per completed line through center
    - 240 per completed line not using center
    - 45 per marked cell that is not part of any completed line
    """
    completed = [ln for ln in all_lines() if line_complete(board, ln)]
    cells_in_completed: set[tuple[int, int]] = set()
    total = 0
    for ln in completed:
        if CENTER in ln:
            total += CENTER_LINE_POINTS
        else:
            total += NON_CENTER_LINE_POINTS
        cells_in_completed.update(ln)

    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if board.marked[r][c] and (r, c) not in cells_in_completed:
                # FREE center alone isn't worth 45 if not in a completed line? 
                # Center is always marked; only count if not in a completed line.
                total += MARKED_CELL_POINTS
    return total


def completed_center_line_count(board: BoardState) -> int:
    return sum(1 for ln in center_lines() if line_complete(board, ln))


def line_progress(board: BoardState, line: list[tuple[int, int]]) -> tuple[int, int]:
    """(marked_count, empty_needed)."""
    marked = sum(1 for r, c in line if board.marked[r][c])
    return marked, BOARD_SIZE - marked
