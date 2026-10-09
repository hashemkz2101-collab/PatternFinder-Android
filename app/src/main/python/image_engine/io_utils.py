"""ابزارهای نمایش: پیش‌نمایش نتیجه با مشخص‌کردن محل قطعه."""
from __future__ import annotations

import cv2
import numpy as np

from image_engine import preprocessing as pre


def make_preview(path: str, polygon: list | None, size: int = 300) -> np.ndarray | None:
    """تصویر RGB کوچک‌شده، با کادر قرمز دور محل تطبیق. خطا -> None."""
    try:
        img = pre.load_image(path)
    except pre.ImageLoadError:
        return None
    work, _ = pre.to_working(img)
    out = work.copy()
    thick = max(2, int(round(max(out.shape[:2]) / 160)))
    if polygon:
        pts = np.array(polygon, np.float32).round().astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(out, [pts], True, (40, 40, 230), thick, cv2.LINE_AA)
    h, w = out.shape[:2]
    s = size / float(max(h, w))
    out = cv2.resize(out, (max(1, int(w * s)), max(1, int(h * s))),
                     interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
