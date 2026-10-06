"""Board placement templates (manual layout presets)."""

from __future__ import annotations

from collections import Counter

from .types import BOARD_SIZE, CENTER, JEWEL_TYPES, TEMPLATE_CHATGPT, BoardState


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


def chatgpt_board() -> BoardState:
    errs = validate_template(TEMPLATE_CHATGPT)
    if errs:
        raise ValueError("invalid TEMPLATE_CHATGPT: " + "; ".join(errs))
    return BoardState.from_template(TEMPLATE_CHATGPT)


def placement_plan(template: list[list[str]] | None = None) -> list[tuple[str, list[tuple[int, int]]]]:
    """
    Group cells by jewel for efficient placement:
    select jewel once, then click all its cells.
    Order follows JEWEL_TYPES (panel top→bottom).
    """
    tmpl = template or TEMPLATE_CHATGPT
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
    tmpl = template or TEMPLATE_CHATGPT
    lines = [" | ".join(f"{c:>4}" for c in row) for row in tmpl]
    return "\n".join(lines)
