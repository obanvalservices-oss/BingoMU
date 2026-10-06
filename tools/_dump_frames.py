import sys
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

cap = cv2.VideoCapture(str(ROOT / "VID_20261006_094447.mp4"))
print("fps", cap.get(cv2.CAP_PROP_FPS))
print("frames", int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
print("w", int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), "h", int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
# sample a few times and report mean brightness of center region
for ms in [20000, 35000, 50000, 80000, 120000]:
    cap.set(cv2.CAP_PROP_POS_MSEC, ms)
    ok, frame = cap.read()
    if not ok:
        print(ms, "FAIL")
        continue
    h, w = frame.shape[:2]
    cx0, cy0 = w // 4, h // 6
    cx1, cy1 = 3 * w // 4, 5 * h // 6
    center = frame[cy0:cy1, cx0:cx1]
    path = ROOT / "assets" / "calibration" / f"raw_{ms}.png"
    cv2.imwrite(str(path), frame)
    # also write a scaled preview
    preview = cv2.resize(frame, (960, int(960 * h / w)))
    cv2.imwrite(str(ROOT / "assets" / "calibration" / f"preview_{ms}.png"), preview)
    print(ms, "shape", frame.shape, "mean", float(np.mean(center)), "saved", path.name)
cap.release()
