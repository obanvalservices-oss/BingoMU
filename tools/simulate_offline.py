"""
Offline full-game simulation (no screen / clicks).

Uses a synthetic board + random draws to exercise heuristic/Monte Carlo
toward the 1000+ target and writes a JSONL log like the live bot.

  python tools/simulate_offline.py
  python tools/simulate_offline.py --games 20 --sims 1500
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.logger import GameLogger
from src.solver.montecarlo import JewelPriors, choose_cell
from src.solver.scoring import score_board
from src.patterns import chatgpt_board
from src.types import (
    DRAWS_PER_GAME,
    JEWEL_TYPES,
    TARGET_SCORE,
    BoardState,
    DecisionRecord,
    GameRecord,
)


def random_board(rng: random.Random) -> BoardState:
    """Deal 24 jewels (4 of each type) onto the board."""
    bag = list(JEWEL_TYPES) * 4
    rng.shuffle(bag)
    b = BoardState()
    i = 0
    for r in range(5):
        for c in range(5):
            if (r, c) == (2, 2):
                continue
            b.cells[r][c] = bag[i]
            i += 1
    return b


def play_game(
    rng: random.Random,
    priors: JewelPriors,
    use_mc: bool,
    n_sims: int,
    use_template: bool = False,
) -> GameRecord:
    board = chatgpt_board() if use_template else random_board(rng)
    record = GameRecord(board=board, placement_mode="template" if use_template else "auto")
    # Sample draw sequence (with replacement using priors)
    for draw_i in range(DRAWS_PER_GAME):
        jewel = priors.sample(rng)
        # Prefer jewels that still have candidates when possible
        if not board.candidates(jewel):
            remaining = [j for j in JEWEL_TYPES if board.candidates(j)]
            if not remaining:
                break
            jewel = rng.choice(remaining)
        record.draws.append(jewel)
        cell, e, p, method = choose_cell(
            board, jewel, draw_index=draw_i, priors=priors, use_mc=use_mc, n_sims=n_sims
        )
        cands = board.candidates(jewel)
        if cell is None:
            continue
        record.decisions.append(
            DecisionRecord(
                draw_index=draw_i,
                jewel=jewel,
                chosen=cell,
                candidates=cands,
                expected_score=e,
                p_ge_1000=p,
                method=method,
            )
        )
        board.mark(*cell)
    record.final_score = score_board(board)
    record.target_met = record.final_score >= TARGET_SCORE
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=10)
    ap.add_argument("--sims", type=int, default=800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-mc", action="store_true")
    ap.add_argument("--template", action="store_true", help="Use ChatGPT board pattern")
    ap.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    priors = JewelPriors.from_logs(str(args.log_dir))
    logger = GameLogger(args.log_dir)
    hits = 0
    scores: list[int] = []
    for i in range(args.games):
        rec = play_game(
            rng,
            priors,
            use_mc=not args.no_mc,
            n_sims=args.sims,
            use_template=args.template,
        )
        logger.log_game(rec)
        scores.append(rec.final_score)
        hits += int(rec.target_met)
        print(
            f"game {i+1:02d}: score={rec.final_score:4d} "
            f"target={'YES' if rec.target_met else 'no ':3} "
            f"draws={len(rec.draws)} method={rec.decisions[-1].method if rec.decisions else '-'}"
        )

    avg = sum(scores) / max(len(scores), 1)
    print(f"\navg={avg:.1f}  hit_rate={hits}/{args.games} ({100*hits/args.games:.0f}%)  log={logger.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
