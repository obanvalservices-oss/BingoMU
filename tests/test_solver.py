"""Unit tests for scoring, patterns, and solver."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.types import (
    JEWEL_TYPES,
    TARGET_SCORE,
    TEMPLATE_CHATGPT,
    BoardState,
)
from src.patterns import chatgpt_board, placement_plan, validate_template
from src.solver.scoring import score_board, all_lines, center_lines
from src.solver.heuristic import choose_heuristic
from src.solver.montecarlo import choose_monte_carlo, JewelPriors, choose_cell


def make_board(layout: list[list[str]]) -> BoardState:
    return BoardState.from_template(layout)


SAMPLE = [
    ["B", "L", "C", "CR", "S"],
    ["H", "B", "L", "C", "CR"],
    ["S", "H", "FREE", "B", "L"],
    ["C", "CR", "S", "H", "B"],
    ["L", "C", "CR", "S", "H"],
]


class TestPattern(unittest.TestCase):
    def test_chatgpt_valid(self):
        self.assertEqual(validate_template(TEMPLATE_CHATGPT), [])

    def test_chatgpt_board(self):
        b = chatgpt_board()
        self.assertEqual(b.cells[2][2], "FREE")
        self.assertEqual(b.cells[0][0], "S")
        self.assertEqual(b.cells[0][2], "B")
        self.assertEqual(b.cells[1][1], "C")

    def test_placement_plan_four_each(self):
        plan = placement_plan()
        self.assertEqual(len(plan), 6)
        for jewel, cells in plan:
            self.assertEqual(len(cells), 4, jewel)
            self.assertIn(jewel, JEWEL_TYPES)


class TestScoring(unittest.TestCase):
    def test_center_free_marked(self):
        b = make_board(SAMPLE)
        self.assertTrue(b.marked[2][2])
        self.assertEqual(b.cells[2][2], "FREE")

    def test_empty_score_is_45_for_center_only(self):
        b = make_board(SAMPLE)
        self.assertEqual(score_board(b), 45)

    def test_full_center_row_scores_312(self):
        b = make_board(SAMPLE)
        for c in range(5):
            b.mark(2, c)
        self.assertEqual(score_board(b), 312)

    def test_non_center_line(self):
        b = make_board(SAMPLE)
        for c in range(5):
            b.mark(0, c)
        self.assertEqual(score_board(b), 240 + 45)

    def test_line_counts(self):
        self.assertEqual(len(all_lines()), 12)
        self.assertEqual(len(center_lines()), 4)


class TestSolver(unittest.TestCase):
    def test_candidates(self):
        b = make_board(SAMPLE)
        self.assertEqual(len(b.candidates("B")), 4)

    def test_heuristic(self):
        b = make_board(SAMPLE)
        cell, score, p = choose_heuristic(b, "S")
        self.assertIsNotNone(cell)
        self.assertIn(cell, b.candidates("S"))

    def test_monte_carlo(self):
        b = make_board(SAMPLE)
        cell, e, p = choose_monte_carlo(b, "B", draws_remaining_after=10, n_sims=200, seed=1)
        self.assertIsNotNone(cell)
        self.assertIn(cell, b.candidates("B"))

    def test_choose_cell(self):
        b = make_board(SAMPLE)
        cell, e, p, method = choose_cell(b, "L", draw_index=0, use_mc=True, n_sims=100)
        self.assertIn(method, ("monte_carlo", "heuristic"))
        self.assertIsNotNone(cell)

    def test_target_constant(self):
        self.assertEqual(TARGET_SCORE, 1000)
        self.assertEqual(len(JEWEL_TYPES), 6)


class TestPriors(unittest.TestCase):
    def test_uniform_sums_to_one(self):
        p = JewelPriors.uniform()
        self.assertAlmostEqual(sum(p.probs.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
