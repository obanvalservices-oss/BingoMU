"""Monte Carlo decision policy — same remaining-draw / center-feasible rules as heuristic."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from ..types import (
    JEWEL_TYPES,
    BoardState,
    DRAWS_PER_GAME,
    TARGET_SCORE,
)
from ..logger import empirical_jewel_priors
from .scoring import score_board, center_lines, line_complete
from .heuristic import (
    candidate_pool,
    cell_has_feasible_center,
    cell_potential,
    choose_heuristic,
)


@dataclass
class JewelPriors:
    probs: dict[str, float] = field(default_factory=dict)
    learned: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.probs:
            n = len(JEWEL_TYPES)
            self.probs = {j: 1.0 / n for j in JEWEL_TYPES}
        self._normalize()

    def _normalize(self) -> None:
        s = sum(self.probs.get(j, 0.0) for j in JEWEL_TYPES) or 1.0
        self.probs = {j: self.probs.get(j, 0.0) / s for j in JEWEL_TYPES}

    @classmethod
    def uniform(cls) -> "JewelPriors":
        return cls()

    @classmethod
    def from_logs(cls, log_dir: str = "logs") -> "JewelPriors":
        from ..history import load_learned_priors

        learned = load_learned_priors()
        overall = learned.get("overall") or empirical_jewel_priors(log_dir)
        return cls(probs=dict(overall), learned=learned)

    def sample(self, rng: random.Random, draw_index: int = 0, prev: str | None = None) -> str:
        from ..history import sample_jewel_for_draw

        if self.learned and self.learned.get("games", 0) >= 2:
            return sample_jewel_for_draw(draw_index, prev, self.learned, rng)
        jewels = list(JEWEL_TYPES)
        weights = [self.probs[j] for j in jewels]
        return rng.choices(jewels, weights=weights, k=1)[0]


def _pick_for_playout(
    board: BoardState, cands: list[tuple[int, int]], draws_after: int
) -> tuple[int, int]:
    """Playout policy mirrors heuristic potential with remaining draws."""
    return max(
        cands,
        key=lambda cell: cell_potential(
            board, *cell, draws_remaining_after=draws_after
        ),
    )


def _simulate_rest(
    board: BoardState,
    draws_left: int,
    priors: JewelPriors,
    rng: random.Random,
    start_draw_index: int = 0,
) -> int:
    """Fast playout using remaining-aware potential + learned priors."""
    b = board.clone()
    prev: str | None = None
    for k in range(draws_left):
        left_after = draws_left - k - 1
        jewel = priors.sample(rng, draw_index=start_draw_index + k, prev=prev)
        cands = b.candidates(jewel)
        if not cands:
            found = False
            for j in JEWEL_TYPES:
                cands = b.candidates(j)
                if cands:
                    jewel = j
                    found = True
                    break
            if not found:
                break
        pool = candidate_pool(b, jewel, draws_remaining_after=left_after) or cands
        b.mark(*_pick_for_playout(b, pool, left_after))
        prev = jewel
    return score_board(b)


def choose_monte_carlo(
    board: BoardState,
    jewel: str,
    draws_remaining_after: int,
    priors: Optional[JewelPriors] = None,
    n_sims: int = 2000,
    seed: Optional[int] = None,
) -> tuple[Optional[tuple[int, int]], float, float]:
    """Evaluate candidates with MC inside the remaining-draw candidate pool."""
    priors = priors or JewelPriors.uniform()
    cands = candidate_pool(board, jewel, draws_remaining_after) or board.candidates(jewel)
    if not cands:
        return None, 0.0, 0.0

    rng = random.Random(seed)
    per = max(20, n_sims // max(len(cands), 1))

    best_cell = None
    best_key = float("-inf")
    best_e = 0.0
    best_p = 0.0

    for cell in cands:
        scores: list[int] = []
        for _ in range(per):
            b = board.clone()
            b.mark(*cell)
            scores.append(
                _simulate_rest(
                    b,
                    draws_remaining_after,
                    priors,
                    rng,
                    start_draw_index=DRAWS_PER_GAME - draws_remaining_after,
                )
            )
        e = sum(scores) / len(scores)
        p = sum(1 for s in scores if s >= TARGET_SCORE) / len(scores)
        immediate = cell_potential(
            board, *cell, draws_remaining_after=draws_remaining_after
        )
        key = immediate * 10.0 + p * 10000.0 + e
        if key > best_key:
            best_key = key
            best_cell = cell
            best_e = e
            best_p = p

    return best_cell, best_e, best_p


def choose_cell(
    board: BoardState,
    jewel: str,
    draw_index: int,
    total_draws: int = DRAWS_PER_GAME,
    priors: Optional[JewelPriors] = None,
    use_mc: bool = True,
    n_sims: int = 2000,
) -> tuple[Optional[tuple[int, int]], float, float, str]:
    """
    Unified chooser. Center lines win only when still completable with draws left.
    """
    remaining_after = max(0, total_draws - draw_index - 1)
    h_cell, h_e, h_p = choose_heuristic(
        board, jewel, draws_remaining_after=remaining_after
    )

    if remaining_after <= 1 or len(board.candidates(jewel)) <= 1:
        return h_cell, h_e, h_p, "heuristic"

    if use_mc and remaining_after > 0:
        cell, e, p = choose_monte_carlo(
            board,
            jewel,
            remaining_after,
            priors=priors,
            n_sims=n_sims,
        )
        # Prefer heuristic only if it completes a FEASIBLE center line now
        if h_cell is not None:

            def center_completes_now(cell_: tuple[int, int] | None) -> int:
                if cell_ is None:
                    return 0
                b = board.clone()
                b.mark(*cell_)
                return sum(
                    1
                    for ln in center_lines()
                    if cell_ in ln and line_complete(b, ln)
                )

            if center_completes_now(h_cell) > center_completes_now(cell):
                if cell_has_feasible_center(board, h_cell, remaining_after):
                    return h_cell, h_e, h_p, "heuristic_center"
        return cell, e, p, "monte_carlo"

    return h_cell, h_e, h_p, "heuristic"
