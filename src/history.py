"""Persistent game history + learned draw-sequence priors for feedback."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .types import DRAWS_PER_GAME, JEWEL_TYPES, GameRecord


DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parent.parent / "logs" / "history.jsonl"
)
DEFAULT_LEARNED_PATH = (
    Path(__file__).resolve().parent.parent / "logs" / "learned_priors.json"
)


def append_game_history(
    record: GameRecord,
    path: str | Path | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> Path:
    """Append one finished game to the durable history JSONL."""
    p = Path(path) if path else DEFAULT_HISTORY_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "placement_mode": record.placement_mode,
        "draws": list(record.draws),
        "board": record.board.to_dict(),
        "final_score": record.final_score,
        "target_met": record.target_met,
        "decisions": [
            {
                "draw_index": d.draw_index,
                "jewel": d.jewel,
                "chosen": list(d.chosen),
                "method": d.method,
                "expected_score": d.expected_score,
            }
            for d in record.decisions
        ],
    }
    if extra:
        payload.update(extra)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    return p


def load_history(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else DEFAULT_HISTORY_PATH
    if not p.exists():
        return []
    games: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "draws" in obj:
                games.append(obj)
    return games


def rebuild_learned_priors(
    history_path: str | Path | None = None,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Stream history.jsonl once (no giant list in RAM).
    Build overall / by_draw_index / transitions priors.
    """
    p = Path(history_path) if history_path else DEFAULT_HISTORY_PATH
    overall: Counter[str] = Counter()
    by_idx: list[Counter[str]] = [Counter() for _ in range(DRAWS_PER_GAME)]
    trans: dict[str, Counter[str]] = {j: Counter() for j in JEWEL_TYPES}
    n_games = 0

    if p.exists():
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                draws_raw = obj.get("draws")
                if not isinstance(draws_raw, list):
                    continue
                draws = [d for d in draws_raw if d in JEWEL_TYPES]
                if not draws:
                    continue
                n_games += 1
                for i, j in enumerate(draws):
                    overall[j] += 1
                    if i < DRAWS_PER_GAME:
                        by_idx[i][j] += 1
                    if i > 0:
                        trans[draws[i - 1]][j] += 1

    def norm_counter(c: Counter[str]) -> dict[str, float]:
        total = sum(c.values())
        if total == 0:
            return {j: 1.0 / len(JEWEL_TYPES) for j in JEWEL_TYPES}
        return {j: c.get(j, 0) / total for j in JEWEL_TYPES}

    learned = {
        "games": n_games,
        "total_draws": int(sum(overall.values())),
        "overall": norm_counter(overall),
        "by_draw_index": [norm_counter(c) for c in by_idx],
        "transitions": {a: norm_counter(trans[a]) for a in JEWEL_TYPES},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = Path(out_path) if out_path else DEFAULT_LEARNED_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(learned, indent=2) + "\n", encoding="utf-8")
    return learned


def load_learned_priors(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_LEARNED_PATH
    if not p.exists():
        return rebuild_learned_priors()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return rebuild_learned_priors()


def history_summary(path: str | Path | None = None) -> str:
    """One-pass summary — does not keep all games in memory."""
    p = Path(path) if path else DEFAULT_HISTORY_PATH
    if not p.exists():
        return "Sin historial aún."
    n = 0
    score_sum = 0
    hits = 0
    modes: Counter[str] = Counter()
    last_draws: list[str] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "draws" not in obj:
                continue
            n += 1
            score_sum += int(obj.get("final_score") or 0)
            if obj.get("target_met"):
                hits += 1
            modes[obj.get("placement_mode", "?")] += 1
            last_draws = list(obj.get("draws") or [])
    if n == 0:
        return "Sin historial aún."
    avg = score_sum / n
    seq = " → ".join(last_draws[:8])
    if len(last_draws) > 8:
        seq += "…"
    return (
        f"Partidas: {n} | ≥1000: {hits} ({100 * hits / n:.0f}%) | "
        f"avg score: {avg:.0f} | modes: {dict(modes)}\n"
        f"Última secuencia: {seq}"
    )


def sample_jewel_for_draw(
    draw_index: int,
    prev: Optional[str],
    learned: Optional[dict[str, Any]],
    rng,
) -> str:
    """Sample next jewel using position + transition priors when history exists."""
    import random

    rng = rng or random.Random()
    learned = learned or {}
    weights = {j: 1.0 for j in JEWEL_TYPES}

    overall = learned.get("overall") or {}
    by_idx = learned.get("by_draw_index") or []
    trans = learned.get("transitions") or {}

    for j in JEWEL_TYPES:
        w = float(overall.get(j, 1.0 / len(JEWEL_TYPES)))
        if 0 <= draw_index < len(by_idx):
            w = 0.55 * w + 0.45 * float(by_idx[draw_index].get(j, w))
        if prev and prev in trans:
            w = 0.6 * w + 0.4 * float(trans[prev].get(j, w))
        weights[j] = max(1e-6, w)

    jewels = list(JEWEL_TYPES)
    return rng.choices(jewels, weights=[weights[j] for j in jewels], k=1)[0]
