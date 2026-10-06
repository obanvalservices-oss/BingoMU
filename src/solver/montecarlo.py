"""Monte Carlo decision policy with learnable jewel priors."""

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
from .scoring import score_board, center_lines
from .heuristic import choose_heuristic


@dataclass
class JewelPriors:
    probs: dict[str, float] = field(default_factory=dict)

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
        return cls(empirical_jewel_priors(log_dir))

    def sample(self, rng: random.Random) -> str:
        jewels = list(JEWEL_TYPES)
        weights = [self.probs[j] for j in jewels]
        return rng.choices(jewels, weights=weights, k=1)[0]


def _simulate_rest(
    board: BoardState,
    draws_left: int,
    priors: JewelPriors,
    rng: random.Random,
) -> int:
    """Fast random-greedy playout for remaining draws."""
    b = board.clone()
    for _ in range(draws_left):
        jewel = priors.sample(rng)
        cands = b.candidates(jewel)
        if not cands:
            # try any remaining jewel type
            found = False
            for j in JEWEL_TYPES:
                cands = b.candidates(j)
                if cands:
                    jewel = j
                    found = True
                    break
            if not found:
                break
        # Fast: pick candidate that lies on most incomplete center lines
        best = cands[0]
        best_v = -1
        for cell in cands:
            v = sum(1 for ln in center_lines() if cell in ln and not all(b.marked[r][c] for r, c in ln))
            if v > best_v:
                best_v = v
                best = cell
        b.mark(*best)
    return score_board(b)


def choose_monte_carlo(
    board: BoardState,
    jewel: str,
    draws_remaining_after: int,
    priors: Optional[JewelPriors] = None,
    n_sims: int = 2000,
    seed: Optional[int] = None,
) -> tuple[Optional[tuple[int, int]], float, float]:
    """
    For each candidate cell of `jewel`, run n_sims / len(cands) playouts.
    Returns (best_cell, E[score], P(score >= 1000)).
    """
    priors = priors or JewelPriors.uniform()
    cands = board.candidates(jewel)
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
            scores.append(_simulate_rest(b, draws_remaining_after, priors, rng))
        e = sum(scores) / len(scores)
        p = sum(1 for s in scores if s >= TARGET_SCORE) / len(scores)
        # Prefer P(hit 1000), then expected score
        key = p * 10000.0 + e
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
    """Unified chooser. draw_index is 0-based index of current draw."""
    remaining_after = max(0, total_draws - draw_index - 1)
    if use_mc and remaining_after > 0 and len(board.candidates(jewel)) > 1:
        cell, e, p = choose_monte_carlo(
            board, jewel, remaining_after, priors=priors, n_sims=n_sims
        )
        return cell, e, p, "monte_carlo"
    cell, e, p = choose_heuristic(board, jewel)
    return cell, e, p, "heuristic"
