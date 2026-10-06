"""Jewel classification: template match (primary) + HSV color (fallback)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from ..capture import crop
from ..types import JEWEL_TYPES, Calibration, Rect


DEFAULT_PROFILES: dict[str, dict] = {
    "B": {"h_ranges": [(140, 170)], "s_min": 60, "v_min": 70, "v_max": 255},
    "S": {"h_ranges": [(120, 145)], "s_min": 50, "v_min": 40, "v_max": 255},
    "CR": {"h_ranges": [(8, 28)], "s_min": 40, "v_min": 40, "v_max": 210},
    "H": {"h_ranges": [(0, 179)], "s_min": 0, "s_max": 55, "v_min": 50, "v_max": 180},
    "L": {"h_ranges": [(85, 110)], "s_min": 40, "v_min": 80, "v_max": 255},
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
    patch = bgr[m : h - m, m : w - m]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    total = float(patch.shape[0] * patch.shape[1]) or 1.0
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


def jewel_features(bgr: np.ndarray, size: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """HSV 2D hist + gray patch — same idea as friend's portable bot."""
    im = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).astype(np.float32)
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    return hist, gray


def expand_rect(rect: Rect, pad: int, frame_w: int, frame_h: int) -> Rect:
    x0 = max(0, rect.x - pad)
    y0 = max(0, rect.y - pad)
    x1 = min(frame_w, rect.x + rect.w + pad)
    y1 = min(frame_h, rect.y + rect.h + pad)
    return Rect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def save_jewel_templates_from_frame(
    frame: np.ndarray,
    cal: Calibration,
    out_dir: str | Path,
    pad: int = 6,
) -> list[str]:
    """
    Crop each calibrated right-panel jewel button from `frame` and save as
    assets/templates/{B,S,CR,H,L,C}.png
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fh, fw = frame.shape[:2]
    saved: list[str] = []
    for code in JEWEL_TYPES:
        if code not in cal.jewel_btns:
            continue
        rect = expand_rect(cal.jewel_btns[code], pad, fw, fh)
        # Prefer a slightly taller crop centered on the click (icon + gem)
        half = max(rect.w, rect.h, 22) // 2 + pad
        cx, cy = rect.center
        x0 = max(0, cx - half)
        y0 = max(0, cy - half)
        x1 = min(fw, cx + half)
        y1 = min(fh, cy + half)
        patch = frame[y0:y1, x0:x1].copy()
        if patch.size == 0:
            continue
        path = out / f"{code}.png"
        cv2.imwrite(str(path), patch)
        saved.append(code)
        print(f"  template {code} → {path} ({patch.shape[1]}x{patch.shape[0]})")
    return saved


class JewelClassifier:
    def __init__(
        self,
        profiles: Optional[dict] = None,
        template_dir: str | Path | None = None,
        min_score: float = 0.08,
        tmpl_min: float = 0.42,
        tmpl_margin: float = 0.05,
    ) -> None:
        self.profiles = profiles or DEFAULT_PROFILES
        self.min_score = min_score
        self.tmpl_min = tmpl_min
        self.tmpl_margin = tmpl_margin
        self.templates: dict[str, np.ndarray] = {}
        self.template_feats: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        if template_dir:
            self._load_templates(Path(template_dir))

    def _load_templates(self, folder: Path) -> None:
        for name in JEWEL_TYPES:
            for ext in (".png", ".jpg", ".bmp"):
                p = folder / f"{name}{ext}"
                if not p.exists():
                    continue
                img = cv2.imread(str(p))
                if img is None:
                    continue
                self.templates[name] = img
                self.template_feats[name] = [jewel_features(img)]
                break
        if self.templates:
            print(f"Jewel templates loaded: {sorted(self.templates.keys())}")

    def has_templates(self) -> bool:
        return len(self.templates) >= 4

    def match_templates(self, bgr: np.ndarray) -> tuple[Optional[str], float, float]:
        """
        Returns (best_label, best_score, margin_vs_second).
        Score blends HSV-hist correlation + gray NCC (friend-bot style).
        """
        if not self.template_feats or bgr is None or bgr.size == 0:
            return None, 0.0, 0.0
        h, g = jewel_features(bgr)
        scores: dict[str, float] = {}
        for name, feats in self.template_feats.items():
            vals = []
            for h2, g2 in feats:
                hc = float(cv2.compareHist(h, h2, cv2.HISTCMP_CORREL))
                if np.isnan(hc):
                    hc = 0.0
                g2_r = g2 if g2.shape == g.shape else cv2.resize(g2, (g.shape[1], g.shape[0]))
                res = cv2.matchTemplate(g, g2_r, cv2.TM_CCOEFF_NORMED)
                gc = float(res[0, 0]) if res.size else -1.0
                vals.append(0.65 * hc + 0.35 * gc)
            if vals:
                scores[name] = max(vals)
        if not scores:
            return None, 0.0, 0.0
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best, best_s = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        return best, best_s, best_s - second

    def classify(self, cell_bgr: np.ndarray, allow_free: bool = False) -> Optional[str]:
        if cell_bgr is None or cell_bgr.size == 0:
            return None
        if allow_free and is_free_center(cell_bgr):
            return "FREE"

        # 1) Template match first (reliable when calibrated crops exist)
        if self.template_feats:
            label, score, margin = self.match_templates(cell_bgr)
            if label and score >= self.tmpl_min and margin >= self.tmpl_margin:
                return label
            # Strong absolute score even with tight margin
            if label and score >= 0.62:
                return label

        # 2) Color fallback
        color_scores = dominant_jewel_score(cell_bgr, self.profiles)
        chromatic = {k: v for k, v in color_scores.items() if k != "H"}
        best_color, best_cs = max(chromatic.items(), key=lambda kv: kv[1])
        grey_score = color_scores.get("H", 0.0)
        if best_cs < self.min_score:
            if grey_score >= max(0.15, self.min_score * 2):
                return "H"
            # weak template without margin still better than nothing
            if self.template_feats:
                label, score, _ = self.match_templates(cell_bgr)
                if label and score >= 0.35:
                    return label
            return None
        return best_color

    def classify_draw_roi(self, roi_bgr: np.ndarray) -> Optional[str]:
        """Draw icon: prefer templates; disambiguate Chaos(C) vs Creation(CR)."""
        if roi_bgr is None or roi_bgr.size == 0:
            return None
        if self.template_feats:
            label, score, margin = self.match_templates(roi_bgr)
            if label and score >= 0.38:
                # Chaos vs Creation are the frequent confusion pair
                if label in ("C", "CR") and self.template_feats.get("C") and self.template_feats.get("CR"):
                    c_lab, c_sc, _ = self._score_one(roi_bgr, "C")
                    cr_lab, cr_sc, _ = self._score_one(roi_bgr, "CR")
                    # Yellow/bright → Chaos; brown/darker → Creation
                    hsv = cv2.cvtColor(
                        cv2.resize(roi_bgr, (40, 40)), cv2.COLOR_BGR2HSV
                    )
                    mean_v = float(hsv[:, :, 2].mean())
                    mean_s = float(hsv[:, :, 1].mean())
                    if abs(c_sc - cr_sc) < 0.12:
                        if mean_v >= 140 and mean_s >= 80:
                            label, score = "C", c_sc
                        elif mean_v < 130:
                            label, score = "CR", cr_sc
                        elif c_sc >= cr_sc:
                            label, score = "C", c_sc
                        else:
                            label, score = "CR", cr_sc
                if score >= 0.38 and (margin >= 0.04 or label in ("C", "CR")):
                    return label
            if label and score >= 0.55:
                return label
        return self.classify(roi_bgr)

    def _score_one(self, bgr: np.ndarray, name: str) -> tuple[Optional[str], float, float]:
        feats = self.template_feats.get(name)
        if not feats:
            return None, 0.0, 0.0
        h, g = jewel_features(bgr)
        vals = []
        for h2, g2 in feats:
            hc = float(cv2.compareHist(h, h2, cv2.HISTCMP_CORREL))
            if np.isnan(hc):
                hc = 0.0
            g2_r = g2 if g2.shape == g.shape else cv2.resize(g2, (g.shape[1], g.shape[0]))
            res = cv2.matchTemplate(g, g2_r, cv2.TM_CCOEFF_NORMED)
            gc = float(res[0, 0]) if res.size else -1.0
            vals.append(0.65 * hc + 0.35 * gc)
        sc = max(vals) if vals else 0.0
        return name, sc, 0.0
