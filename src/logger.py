"""JSONL game logging for Monte Carlo prior learning."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import DecisionRecord, GameRecord


class GameLogger:
    def __init__(self, log_dir: str | Path = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.path = self.log_dir / f"games_{stamp}.jsonl"

    def log_game(self, record: GameRecord) -> None:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "board": record.board.to_dict(),
            "draws": record.draws,
            "decisions": [
                {
                    "draw_index": d.draw_index,
                    "jewel": d.jewel,
                    "chosen": list(d.chosen),
                    "candidates": [list(c) for c in d.candidates],
                    "expected_score": d.expected_score,
                    "p_ge_1000": d.p_ge_1000,
                    "method": d.method,
                }
                for d in record.decisions
            ],
            "final_score": record.final_score,
            "target_met": record.target_met,
            "placement_mode": record.placement_mode,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        # Durable history + rebuild learned priors for next games
        try:
            from .history import append_game_history, rebuild_learned_priors

            append_game_history(record)
            rebuild_learned_priors()
        except Exception as e:
            self.log_event("history_write_failed", error=str(e))

    def log_event(self, event: str, **kwargs: Any) -> None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")


def load_all_games(log_dir: str | Path = "logs") -> list[dict]:
    games: list[dict] = []
    for path in sorted(Path(log_dir).glob("games_*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "board" in obj:
                    games.append(obj)
    return games


def empirical_jewel_priors(log_dir: str | Path = "logs") -> dict[str, float]:
    """Frequency of drawn jewels across logged games."""
    from collections import Counter
    from .types import JEWEL_TYPES

    counts: Counter[str] = Counter()
    for g in load_all_games(log_dir):
        for j in g.get("draws", []):
            if j in JEWEL_TYPES:
                counts[j] += 1
    total = sum(counts.values())
    if total == 0:
        n = len(JEWEL_TYPES)
        return {j: 1.0 / n for j in JEWEL_TYPES}
    return {j: counts.get(j, 0) / total for j in JEWEL_TYPES}
