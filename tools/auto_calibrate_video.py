"""Dump a video frame and auto-detect a dark rectangular overlay as Jewel Bingo ROI."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.types import Calibration, Rect


def find_overlay(frame: np.ndarray) -> Rect | None:
    """Find large dark UI panel (Jewel Bingo) via edges + contours."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = 0.0
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        if area < (w * h) * 0.05 or area > (w * h) * 0.7:
            continue
        aspect = bw / max(bh, 1)
        if aspect < 0.55 or aspect > 1.8:
            continue
        # Prefer somewhat centered
        cx, cy = x + bw / 2, y + bh / 2
        center_dist = abs(cx - w / 2) / w + abs(cy - h / 2) / h
        score = area / (1 + 3 * center_dist)
        # Prefer darker interior (UI panels)
        patch = gray[y : y + bh, x : x + bw]
        if patch.size and float(np.mean(patch)) > 140:
            continue
        if score > best_score:
            best_score = score
            best = Rect(x, y, bw, bh)
    return best


def cal_from_overlay(ov: Rect) -> Calibration:
    ox, oy, ow, oh = ov.x, ov.y, ov.w, ov.h
    grid = Rect(
        ox + int(ow * 0.06),
        oy + int(oh * 0.12),
        int(ow * 0.55),
        int(oh * 0.50),
    )
    boxes = Rect(
        ox + int(ow * 0.08),
        oy + int(oh * 0.70),
        int(ow * 0.55),
        int(oh * 0.16),
    )
    auto_btn = Rect(ox + int(ow * 0.66), oy + int(oh * 0.78), int(ow * 0.28), int(oh * 0.10))
    start_btn = Rect(ox + int(ow * 0.66), oy + int(oh * 0.66), int(ow * 0.28), int(oh * 0.10))
    reward_btn = Rect(ox + int(ow * 0.35), oy + int(oh * 0.85), int(ow * 0.30), int(oh * 0.10))
    score_roi = Rect(ox + int(ow * 0.66), oy + int(oh * 0.38), int(ow * 0.30), int(oh * 0.12))
    draw_roi = Rect(ox + int(ow * 0.66), oy + int(oh * 0.14), int(ow * 0.28), int(oh * 0.18))
    return Calibration(
        overlay=ov,
        grid=grid,
        boxes=boxes,
        auto_btn=auto_btn,
        start_btn=start_btn,
        reward_btn=reward_btn,
        score_roi=score_roi,
        draw_jewel_roi=draw_roi,
    )


def main() -> None:
    video = ROOT / "VID_20261006_094447.mp4"
    cap = cv2.VideoCapture(str(video))
    print("fps", cap.get(cv2.CAP_PROP_FPS), "frames", int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    # Try several timestamps where bingo is visible
    for ms in (30000, 35000, 40000, 45000):
        cap.set(cv2.CAP_PROP_POS_MSEC, ms)
        ok, frame = cap.read()
        if not ok:
            print(ms, "fail")
            continue
        path = ROOT / "assets" / "calibration" / f"frame_{ms}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), frame)
        ov = find_overlay(frame)
        print(ms, "shape", frame.shape, "overlay", ov)
        if ov:
            vis = frame.copy()
            cv2.rectangle(vis, (ov.x, ov.y), (ov.x + ov.w, ov.y + ov.h), (0, 255, 0), 3)
            cal = cal_from_overlay(ov)
            for r in (cal.grid, cal.boxes, cal.draw_jewel_roi, cal.score_roi):
                cv2.rectangle(vis, (r.x, r.y), (r.x + r.w, r.y + r.h), (255, 128, 0), 2)
            cv2.imwrite(str(ROOT / "assets" / "calibration" / f"overlay_{ms}.png"), vis)
            out = ROOT / "assets" / "calibration" / "default.json"
            cal.save(str(out))
            print("saved", out)
            break
    cap.release()


if __name__ == "__main__":
    main()
