"""Vision package for Jewel Bingo board / draw detection."""

from .board import BoardReader, cell_rects
from .draw import DrawDetector, MarkedCellDetector
from .score import read_total_score
from .templates import JewelClassifier, load_or_build_color_profiles

__all__ = [
    "BoardReader",
    "cell_rects",
    "DrawDetector",
    "MarkedCellDetector",
    "read_total_score",
    "JewelClassifier",
    "load_or_build_color_profiles",
]
