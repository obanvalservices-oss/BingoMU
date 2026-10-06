"""
Offline vision replay against the reference MP4 (no clicks / no MU required).

  python tools/replay_video.py
  python tools/replay_video.py --ms 35000 --show
  python tools/replay_video.py --scan --step-ms 1000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.capture import VideoCapture, crop
from src.types import Calibration, Rect
from src.vision.board import BoardReader, cell_rects
from src.vision.draw import DrawDetector
from src.vision.score import read_total_score
from src.vision.templates import JewelClassifier


def default_cal() -> Path:
    return ROOT / "assets" / "calibration" / "default.json"


def estimate_rois_from_frame(frame: np.ndarray) -> Calibration:
    """
    Best-effort ROI guess for phone/desktop recordings when no calibration exists.
    Centers on the middle of the frame where Jewel Bingo overlay typically sits.
    """
    h, w = frame.shape[:2]
    # Assume bingo overlay occupies central ~42% width / 55% height of frame
    ow, oh = int(w * 0.42), int(h * 0.55)
    ox, oy = (w - ow) // 2, int(h * 0.12)
    overlay = Rect(ox, oy, ow, oh)
    # Grid: upper 55% of overlay, slightly inset
    gx = ox + int(ow * 0.06)
    gy = oy + int(oh * 0.10)
    gw = int(ow * 0.58)
    gh = int(oh * 0.52)
    grid = Rect(gx, gy, gw, gh)
    boxes = Rect(ox + int(ow * 0.08), oy + int(oh * 0.72), int(ow * 0.55), int(oh * 0.18))
    auto_btn = Rect(ox + int(ow * 0.65), oy + int(oh * 0.82), int(ow * 0.28), int(oh * 0.10))
    start_btn = Rect(ox + int(ow * 0.65), oy + int(oh * 0.70), int(ow * 0.28), int(oh * 0.10))
    reward_btn = Rect(ox + int(ow * 0.35), oy + int(oh * 0.85), int(ow * 0.30), int(oh * 0.10))
    score_roi = Rect(ox + int(ow * 0.68), oy + int(oh * 0.35), int(ow * 0.28), int(oh * 0.12))
    draw_roi = Rect(ox + int(ow * 0.68), oy + int(oh * 0.12), int(ow * 0.25), int(oh * 0.18))
    return Calibration(
        overlay=overlay,
        grid=grid,
        boxes=boxes,
        auto_btn=auto_btn,
        start_btn=start_btn,
        reward_btn=reward_btn,
        score_roi=score_roi,
        draw_jewel_roi=draw_roi,
    )


def annotate(frame: np.ndarray, cal: Calibration, board_cells) -> np.ndarray:
    out = frame.copy()
    for name, r in [
        ("overlay", cal.overlay),
        ("grid", cal.grid),
        ("boxes", cal.boxes),
        ("auto", cal.auto_btn),
        ("start", cal.start_btn),
        ("score", cal.score_roi),
        ("draw", cal.draw_jewel_roi),
    ]:
        cv2.rectangle(out, (r.x, r.y), (r.x + r.w, r.y + r.h), (0, 255, 255), 2)
        cv2.putText(out, name, (r.x, max(15, r.y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

    if board_cells is not None:
        for r in range(5):
            for c in range(5):
                label = board_cells[r][c] or "?"
                cell = cell_rects(cal.grid)[r][c]
                cv2.putText(
                    out,
                    label[:3],
                    (cell.x + 2, cell.y + 14),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (0, 255, 0),
                    1,
                )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, default=ROOT / "VID_20261006_094447.mp4")
    ap.add_argument("--cal", type=Path, default=default_cal())
    ap.add_argument("--ms", type=float, default=35000.0)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--scan", action="store_true", help="Sample frames across the video")
    ap.add_argument("--step-ms", type=float, default=2000.0)
    ap.add_argument("--save-cal-estimate", action="store_true")
    args = ap.parse_args()

    if not args.video.exists():
        print(f"Video not found: {args.video}")
        return 1

    vc = VideoCapture(args.video)
    frame0 = vc.seek_ms(args.ms)
    if frame0 is None:
        frame0 = vc.seek_frame(0)
    if frame0 is None:
        print("Cannot read video frame")
        return 1

    if args.cal.exists():
        cal = Calibration.load(str(args.cal))
        print(f"Loaded calibration: {args.cal}")
    else:
        cal = estimate_rois_from_frame(frame0)
        print("No calibration found — using geometric estimate.")
        if args.save_cal_estimate:
            out = ROOT / "assets" / "calibration" / "default.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            cal.save(str(out))
            print(f"Wrote estimate -> {out}")

    classifier = JewelClassifier(template_dir=ROOT / "assets" / "templates")
    reader = BoardReader(cal, classifier)
    detector = DrawDetector(cal, classifier)

    times = [args.ms]
    if args.scan:
        duration_ms = (vc.frame_count / max(vc.fps, 1)) * 1000
        times = list(np.arange(0, duration_ms, args.step_ms))

    results = []
    for t in times:
        frame = vc.seek_ms(float(t))
        if frame is None:
            continue
        board = reader.read(frame)
        jewel = detector.detect(frame)
        score = read_total_score(frame, cal.score_roi)
        summary = {
            "ms": float(t),
            "draw_jewel": jewel,
            "score_ocr": score,
            "board": board.cells,
        }
        results.append(summary)
        print(f"t={t:.0f}ms draw={jewel} score={score}")
        for row in board.cells:
            print(" ", row)
        if args.show:
            vis = annotate(frame, cal, board.cells)
            # Fit window
            h, w = vis.shape[:2]
            if w > 1280:
                vis = cv2.resize(vis, (1280, int(h * 1280 / w)))
            cv2.imshow("replay", vis)
            if cv2.waitKey(0 if not args.scan else 200) & 0xFF == ord("q"):
                break

    out_json = ROOT / "logs" / "replay_last.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_json}")
    vc.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
