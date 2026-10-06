"""Shared types and constants for Jewel Bingo."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import json


# Scoring rules (user-specified)
CENTER_LINE_POINTS = 312
NON_CENTER_LINE_POINTS = 240
MARKED_CELL_POINTS = 45
TARGET_SCORE = 1000

BOARD_SIZE = 5
CENTER = (2, 2)
DRAWS_PER_GAME = 14

# Official jewel codes (right-panel order: top → bottom)
# B=Bless, S=Soul, CR=Creation, H=Harmony, L=Life, C=Chaos
JEWEL_TYPES = ("B", "S", "CR", "H", "L", "C")

JEWEL_NAMES: dict[str, str] = {
    "B": "Jewel of Bless",
    "S": "Jewel of Soul",
    "CR": "Jewel of Creation",
    "H": "Jewel of Harmony",
    "L": "Jewel of Life",
    "C": "Jewel of Chaos",
}

# ChatGPT-recommended manual placement pattern (center = FREE / MU)
TEMPLATE_CHATGPT: list[list[str]] = [
    ["S", "H", "B", "L", "H"],
    ["CR", "C", "C", "L", "C"],
    ["B", "H", "FREE", "S", "C"],
    ["B", "CR", "CR", "B", "L"],
    ["S", "CR", "H", "S", "L"],
]


class PlacementMode(Enum):
    AUTO = "auto"
    TEMPLATE = "template"


class GameState(Enum):
    IDLE = auto()
    CALIBRATE = auto()
    PRESS_START = auto()
    PLACE_JEWELS = auto()  # auto-place OR manual template
    READ_BOARD = auto()
    PICK_BOX = auto()
    WAIT_DRAW = auto()
    DECIDE_CELL = auto()
    CLICK_CELL = auto()
    ACCEPT_REWARD = auto()
    NO_CARDS = auto()
    ERROR = auto()


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        self.x = int(self.x)
        self.y = int(self.y)
        self.w = int(self.w)
        self.h = int(self.h)

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d: dict) -> "Rect":
        return cls(int(d["x"]), int(d["y"]), int(d["w"]), int(d["h"]))


@dataclass
class Calibration:
    """Screen coordinates (absolute desktop / Remote Desktop window)."""

    overlay: Rect
    grid: Rect
    boxes: Rect  # blue chest / top-left box
    auto_btn: Rect
    start_btn: Rect
    reward_btn: Rect
    score_roi: Rect
    draw_jewel_roi: Rect
    # Right-panel jewel selectors in order B, S, CR, H, L, C
    jewel_btns: dict[str, Rect] = field(default_factory=dict)
    window_title: str = "Chrome Remote Desktop"
    click_delay_s: float = 0.45
    draw_timeout_s: float = 15.0
    post_auto_wait_s: float = 1.5
    place_delay_s: float = 0.45  # between template placement clicks (GRD-safe)


    def to_dict(self) -> dict:
        return {
            "overlay": self.overlay.to_dict(),
            "grid": self.grid.to_dict(),
            "boxes": self.boxes.to_dict(),
            "auto_btn": self.auto_btn.to_dict(),
            "start_btn": self.start_btn.to_dict(),
            "reward_btn": self.reward_btn.to_dict(),
            "score_roi": self.score_roi.to_dict(),
            "draw_jewel_roi": self.draw_jewel_roi.to_dict(),
            "jewel_btns": {k: v.to_dict() for k, v in self.jewel_btns.items()},
            "window_title": self.window_title,
            "click_delay_s": self.click_delay_s,
            "draw_timeout_s": self.draw_timeout_s,
            "post_auto_wait_s": self.post_auto_wait_s,
            "place_delay_s": self.place_delay_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Calibration":
        jewel_btns = {
            k: Rect.from_dict(v) for k, v in d.get("jewel_btns", {}).items()
        }
        return cls(
            overlay=Rect.from_dict(d["overlay"]),
            grid=Rect.from_dict(d["grid"]),
            boxes=Rect.from_dict(d["boxes"]),
            auto_btn=Rect.from_dict(d["auto_btn"]),
            start_btn=Rect.from_dict(d["start_btn"]),
            reward_btn=Rect.from_dict(d["reward_btn"]),
            score_roi=Rect.from_dict(d["score_roi"]),
            draw_jewel_roi=Rect.from_dict(d["draw_jewel_roi"]),
            jewel_btns=jewel_btns,
            window_title=d.get("window_title", "Chrome Remote Desktop"),
            click_delay_s=float(d.get("click_delay_s", 0.45)),
            draw_timeout_s=float(d.get("draw_timeout_s", 8.0)),
            post_auto_wait_s=float(d.get("post_auto_wait_s", 1.5)),
            place_delay_s=float(d.get("place_delay_s", 0.45)),
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Calibration":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


@dataclass
class BoardState:
    """5x5 jewel layout. None = empty/unknown, 'FREE' = center, else jewel code."""

    cells: list[list[Optional[str]]] = field(
        default_factory=lambda: [[None] * BOARD_SIZE for _ in range(BOARD_SIZE)]
    )
    marked: list[list[bool]] = field(
        default_factory=lambda: [[False] * BOARD_SIZE for _ in range(BOARD_SIZE)]
    )

    def __post_init__(self) -> None:
        self.cells[CENTER[0]][CENTER[1]] = "FREE"
        self.marked[CENTER[0]][CENTER[1]] = True

    def clone(self) -> "BoardState":
        return BoardState(
            cells=[row[:] for row in self.cells],
            marked=[row[:] for row in self.marked],
        )

    def candidates(self, jewel: str) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                if not self.marked[r][c] and self.cells[r][c] == jewel:
                    out.append((r, c))
        return out

    def mark(self, r: int, c: int) -> None:
        self.marked[r][c] = True

    def to_dict(self) -> dict:
        return {"cells": self.cells, "marked": self.marked}

    @classmethod
    def from_dict(cls, d: dict) -> "BoardState":
        b = cls()
        b.cells = d["cells"]
        b.marked = d["marked"]
        return b

    @classmethod
    def from_template(cls, template: list[list[str]]) -> "BoardState":
        b = cls()
        for r in range(BOARD_SIZE):
            for c in range(BOARD_SIZE):
                b.cells[r][c] = template[r][c]
                b.marked[r][c] = template[r][c] == "FREE"
        return b


@dataclass
class DecisionRecord:
    draw_index: int
    jewel: str
    chosen: tuple[int, int]
    candidates: list[tuple[int, int]]
    expected_score: float
    p_ge_1000: float
    method: str


@dataclass
class GameRecord:
    board: BoardState
    draws: list[str] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    final_score: int = 0
    target_met: bool = False
    placement_mode: str = "auto"
