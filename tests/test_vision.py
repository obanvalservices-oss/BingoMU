"""Smoke tests for vision helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from src.types import JEWEL_TYPES, Calibration, Rect
from src.vision.templates import JewelClassifier, DEFAULT_PROFILES
from src.vision.board import cell_rects
from src.vision.draw import MarkedCellDetector


class TestVisionUnit(unittest.TestCase):
    def test_profiles_cover_all_jewels(self):
        for j in JEWEL_TYPES:
            self.assertIn(j, DEFAULT_PROFILES)

    def test_classifier_on_synthetic_bless(self):
        import cv2

        hsv = np.zeros((40, 40, 3), dtype=np.uint8)
        hsv[:, :] = (155, 180, 200)  # pink → Bless
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        clf = JewelClassifier(min_score=0.05)
        label = clf.classify(bgr)
        self.assertEqual(label, "B")

    def test_cell_rects_5x5(self):
        grid = Rect(100, 100, 250, 250)
        cells = cell_rects(grid)
        self.assertEqual(len(cells), 5)
        self.assertEqual(cells[4][4].x + cells[4][4].w, 350)

    def test_calibration_with_jewels(self):
        path = ROOT / "assets" / "calibration" / "_test_cal.json"
        btns = {j: Rect(10, 10 + i * 20, 20, 16) for i, j in enumerate(JEWEL_TYPES)}
        cal = Calibration(
            overlay=Rect(1, 2, 3, 4),
            grid=Rect(10, 20, 30, 40),
            boxes=Rect(5, 5, 5, 5),
            auto_btn=Rect(1, 1, 1, 1),
            start_btn=Rect(2, 2, 2, 2),
            reward_btn=Rect(3, 3, 3, 3),
            score_roi=Rect(4, 4, 4, 4),
            draw_jewel_roi=Rect(6, 6, 6, 6),
            jewel_btns=btns,
        )
        cal.save(str(path))
        loaded = Calibration.load(str(path))
        self.assertEqual(set(loaded.jewel_btns.keys()), set(JEWEL_TYPES))
        path.unlink()


if __name__ == "__main__":
    unittest.main()
