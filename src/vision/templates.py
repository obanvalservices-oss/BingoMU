"""Jewel classification via HSV color profiles + optional template matching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..types import JEWEL_TYPES


# HSV profiles keyed by official codes (right-panel order).
# Approximate MU jewel colors — refine via assets/calibration/color_profiles.json
DEFAULT_PROFILES: dict[str, dict] = {
    # Bless — pink / magenta diamond
    "B": {"h_ranges": [(140, 170)], "s_min": 60, "v_min": 70, "v_max": 255},
    # Soul — purple / violet
    "S": {"h_ranges": [(120, 145)], "s_min": 50, "v_min": 40, "v_max": 255},
    # Creation — brown / gold cylinder
    "CR": {"h_ranges": [(8, 28)], "s_min": 40, "v_min": 40, "v_max": 210},
    # Harmony — grey / low saturation
    "H": {"h_ranges": [(0, 179)], "s_min": 0, "s_max": 55, "v_min": 50, "v_max": 180},
    # Life — cyan / light blue
    "L": {"h_ranges": [(85, 110)], "s_min": 40, "v_min": 80, "v_max": 255},
    # Chaos — yellow / orange
    "C": {"h_ranges": [(18, 40)], "s_min": 70, "v_min": 80, "v_max": 255},
}


def load_or_build_color_profiles(path: str | Path | None = None) -> dict:
    if path and Path(path).exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_PROFILES


def _mask_for_profile(hsv: np.ndarray, profile: dict) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    s_max = int(profile.get("s_max", 255))
    for h0, h1 in profile["h_ranges"]:
        lower = np.array([h0, profile["s_min"], profile["v_min"]], dtype=np.uint8)
        upper = np.array([h1, s_max, profile["v_max"]], dtype=np.uint8)
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lower, upper))
    return mask


def dominant_jewel_score(bgr: np.ndarray, profiles: dict) -> dict[str, float]:
    if bgr.size == 0:
        return {j: 0.0 for j in JEWEL_TYPES}
    h, w = bgr.shape[:2]
    m = max(1, min(h, w) // 8)
    crop = bgr[m : h - m, m : w - m]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    total = float(crop.shape[0] * crop.shape[1]) or 1.0
    scores: dict[str, float] = {}
    for name in JEWEL_TYPES:
        mask = _mask_for_profile(hsv, profiles[name])
        scores[name] = float(cv2.countNonZero(mask)) / total
    return scores


def is_free_center(bgr: np.ndarray) -> bool:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([95, 40, 80], dtype=np.uint8), np.array([130, 255, 255], dtype=np.uint8))
    gold = cv2.inRange(hsv, np.array([15, 40, 140], dtype=np.uint8), np.array([40, 255, 255], dtype=np.uint8))
    total = float(bgr.shape[0] * bgr.shape[1] or 1)
    return (cv2.countNonZero(blue) / total) > 0.10 or (cv2.countNonZero(gold) / total) > 0.12


class JewelClassifier:
    def __init__(
        self,
        profiles: Optional[dict] = None,
        template_dir: str | Path | None = None,
        min_score: float = 0.08,
    ) -> None:
        self.profiles = profiles or DEFAULT_PROFILES
        self.min_score = min_score
        self.templates: dict[str, np.ndarray] = {}
        if template_dir:
            self._load_templates(Path(template_dir))

    def _load_templates(self, folder: Path) -> None:
        for name in JEWEL_TYPES:
            for ext in (".png", ".jpg", ".bmp"):
                p = folder / f"{name}{ext}"
                if p.exists():
                    img = cv2.imread(str(p))
                    if img is not None:
                        self.templates[name] = img
                    break

    def classify(self, cell_bgr: np.ndarray, allow_free: bool = False) -> Optional[str]:
        if cell_bgr is None or cell_bgr.size == 0:
            return None
        if allow_free and is_free_center(cell_bgr):
            return "FREE"

        color_scores = dominant_jewel_score(cell_bgr, self.profiles)
        chromatic = {k: v for k, v in color_scores.items() if k != "H"}
        best_color, best_cs = max(chromatic.items(), key=lambda kv: kv[1])
        grey_score = color_scores.get("H", 0.0)
        if best_cs < self.min_score:
            if grey_score >= max(0.15, self.min_score * 2):
                best_color, best_cs = "H", grey_score
            else:
                best_color, best_cs = None, 0.0

        best_tmpl, best_ts = None, -1.0
        if self.templates:
            gray = cv2.cvtColor(cell_bgr, cv2.COLOR_BGR2GRAY)
            for name, tmpl in self.templates.items():
                tg = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
                th, tw = tg.shape[:2]
                ch, cw = gray.shape[:2]
                if th > ch or tw > cw:
                    scale = min(ch / th, cw / tw) * 0.9
                    tg = cv2.resize(tg, (max(1, int(tw * scale)), max(1, int(th * scale))))
                res = cv2.matchTemplate(gray, tg, cv2.TM_CCOEFF_NORMED)
                score = float(res.max()) if res.size else -1.0
                if score > best_ts:
                    best_ts = score
                    best_tmpl = name

        if best_tmpl and best_ts >= 0.55:
            return best_tmpl
        if best_cs is not None and best_cs >= self.min_score:
            return best_color
        return best_color if best_cs and best_cs > 0 else None

    def classify_draw_roi(self, roi_bgr: np.ndarray) -> Optional[str]:
        return self.classify(roi_bgr)
