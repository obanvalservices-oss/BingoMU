"""Load / save the active 5×5 placement pattern (editable without code changes)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from .types import BOARD_SIZE, CENTER, JEWEL_TYPES, TEMPLATE_CHATGPT, BoardState

# Default path relative to project root
DEFAULT_PATTERN_PATH = Path(__file__).resolve().parent.parent / "assets" / "patterns" / "active.json"


def validate_template(template: list[list[str]]) -> list[str]:
    """Return list of error strings (empty = OK). Must be 4 of each jewel + FREE center."""
    errors: list[str] = []
    if len(template) != BOARD_SIZE or any(len(row) != BOARD_SIZE for row in template):
        return ["template must be 5x5"]
    if template[CENTER[0]][CENTER[1]] != "FREE":
        errors.append("center must be FREE")
    flat = [template[r][c] for r in range(BOARD_SIZE) for c in range(BOARD_SIZE)]
    counts = Counter(flat)
    if counts.get("FREE", 0) != 1:
        errors.append(f"expected 1 FREE, got {counts.get('FREE', 0)}")
    for j in JEWEL_TYPES:
        if counts.get(j, 0) != 4:
            errors.append(f"expected 4x {j}, got {counts.get(j, 0)}")
    unknown = set(flat) - set(JEWEL_TYPES) - {"FREE"}
    if unknown:
        errors.append(f"unknown labels: {sorted(unknown)}")
    return errors


def default_template() -> list[list[str]]:
    return [row[:] for row in TEMPLATE_CHATGPT]


def load_active_template(path: str | Path | None = None) -> list[list[str]]:
    """Load pattern from JSON; fall back to built-in ChatGPT preset."""
    p = Path(path) if path else DEFAULT_PATTERN_PATH
    if not p.exists():
        return default_template()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        grid = data.get("grid") if isinstance(data, dict) else data
        if not isinstance(grid, list):
            return default_template()
        tmpl = [[str(cell) for cell in row] for row in grid]
        errs = validate_template(tmpl)
        if errs:
            print(f"WARNING: invalid pattern in {p}: {errs} — using default")
            return default_template()
        return tmpl
    except Exception as e:
        print(f"WARNING: could not load pattern {p}: {e} — using default")
        return default_template()


def save_active_template(
    template: list[list[str]], path: str | Path | None = None, name: str = "custom"
) -> Path:
    errs = validate_template(template)
    if errs:
        raise ValueError("; ".join(errs))
    p = Path(path) if path else DEFAULT_PATTERN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "grid": template,
        "notes": "Editable Jewel Bingo placement. Center must be FREE; 4 of each B/S/CR/H/L/C.",
    }
    p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def board_from_template(template: list[list[str]] | None = None) -> BoardState:
    tmpl = template if template is not None else load_active_template()
    errs = validate_template(tmpl)
    if errs:
        raise ValueError("invalid template: " + "; ".join(errs))
    return BoardState.from_template(tmpl)


def chatgpt_board() -> BoardState:
    """Board from active pattern file (or built-in ChatGPT default)."""
    return board_from_template(load_active_template())


def placement_plan(
    template: list[list[str]] | None = None,
) -> list[tuple[str, list[tuple[int, int]]]]:
    """
    Group cells by jewel for efficient placement:
    select jewel once, then click all its cells.
    """
    tmpl = template if template is not None else load_active_template()
    errs = validate_template(tmpl)
    if errs:
        raise ValueError("; ".join(errs))
    plan: list[tuple[str, list[tuple[int, int]]]] = []
    for jewel in JEWEL_TYPES:
        cells = [
            (r, c)
            for r in range(BOARD_SIZE)
            for c in range(BOARD_SIZE)
            if tmpl[r][c] == jewel
        ]
        plan.append((jewel, cells))
    return plan


def format_template(template: list[list[str]] | None = None) -> str:
    tmpl = template if template is not None else load_active_template()
    lines = [" | ".join(f"{c:>4}" for c in row) for row in tmpl]
    return "\n".join(lines)
