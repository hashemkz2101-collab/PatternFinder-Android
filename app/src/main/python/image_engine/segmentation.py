"""تشخیص خودکار قطعات (اجزای مجزا) و کار با نواحی انتخابی کاربر."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np


@dataclass
class Region:
    """یک قطعه؛ مستطیل (x,y,w,h) و در صورت نیاز چندضلعی (مختصات تصویر کاری)."""

    x: int
    y: int
    w: int
    h: int
    polygon: Optional[list] = None  # [(x, y), ...]
    source: str = "auto"            # auto | manual
    area: int = 0

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    @classmethod
    def from_rect(cls, x, y, w, h, source="manual") -> "Region":
        return cls(int(x), int(y), int(w), int(h), None, source)

    @classmethod
    def from_polygon(cls, pts: Iterable, source="manual") -> "Region":
        p = [(int(round(a)), int(round(b))) for a, b in pts]
        arr = np.array(p, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(arr)
        return cls(x, y, max(1, w), max(1, h), p, source)

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "polygon": self.polygon, "source": self.source}

    def outline(self) -> list:
        if self.polygon:
            return list(self.polygon)
        return [(self.x, self.y), (self.x + self.w, self.y),
                (self.x + self.w, self.y + self.h), (self.x, self.y + self.h)]


def _odd(n: float) -> int:
    n = int(max(3, round(n)))
    return n if n % 2 else n + 1


def mask_from_region(binary: np.ndarray, region: Region) -> Optional[tuple[np.ndarray, tuple[int, int]]]:
    """ماسک فشردهٔ قطعه و مختصات گوشهٔ بالا-چپ آن در تصویر. اگر خالی بود None."""
    H, W = binary.shape[:2]
    x0, y0 = max(0, region.x), max(0, region.y)
    x1, y1 = min(W, region.x + region.w), min(H, region.y + region.h)
    if x1 <= x0 or y1 <= y0:
        return None
    if region.polygon and len(region.polygon) >= 3:
        pm = np.zeros((H, W), np.uint8)
        cv2.fillPoly(pm, [np.array(region.polygon, np.int32)], 255)
        sub = cv2.bitwise_and(binary[y0:y1, x0:x1], pm[y0:y1, x0:x1])
    else:
        sub = binary[y0:y1, x0:x1].copy()
    pts = cv2.findNonZero(sub)
    if pts is None:
        return None
    bx, by, bw, bh = cv2.boundingRect(pts)
    return sub[by:by + bh, bx:bx + bw].copy(), (x0 + bx, y0 + by)


def union_mask(binary: np.ndarray, regions: list[Region]) -> Optional[tuple[np.ndarray, tuple[int, int]]]:
    """اجتماع ماسک چند قطعه (برای ویژگی‌های «کل طرح»). بدون قطعه: کل باینری."""
    H, W = binary.shape[:2]
    if not regions:
        acc = binary
    else:
        acc = np.zeros((H, W), np.uint8)
        for r in regions:
            res = mask_from_region(binary, r)
            if res is None:
                continue
            m, (ox, oy) = res
            acc[oy:oy + m.shape[0], ox:ox + m.shape[1]] |= m
    pts = cv2.findNonZero(acc)
    if pts is None:
        return None
    bx, by, bw, bh = cv2.boundingRect(pts)
    return acc[by:by + bh, bx:bx + bw].copy(), (bx, by)


def detect_regions(
    binary: np.ndarray,
    merge_ratio: float = 0.010,
    min_rel_area: float = 0.03,
    min_abs_ratio: float = 0.0003,
    max_regions: int = 40,
) -> list[Region]:
    """اجزای نزدیک به هم یک قطعه حساب می‌شوند (merge_ratio نسبت به بزرگ‌ترین ضلع)."""
    H, W = binary.shape[:2]
    if not np.any(binary):
        return []
    k = _odd(merge_ratio * max(H, W))
    dil = cv2.dilate(binary, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dil, connectivity=8)

    cands: list[tuple[int, Region]] = []
    for i in range(1, n):
        grp = (labels == i)
        gm = np.where(grp, binary, 0).astype(np.uint8)
        area = int(cv2.countNonZero(gm))
        if area == 0:
            continue
        x, y, w, h = cv2.boundingRect(cv2.findNonZero(gm))
        # قاب اسکنر / حاشیهٔ بزرگ و توخالی را کنار بگذار
        if w > 0.95 * W and h > 0.95 * H and area < 0.25 * w * h:
            continue
        # چندضلعی ناحیه (کانتور بیرونی ناحیهٔ گسترده‌شده)
        cs, _ = cv2.findContours(grp.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        poly = None
        if cs:
            c = max(cs, key=cv2.contourArea)
            ap = cv2.approxPolyDP(c, 0.004 * cv2.arcLength(c, True), True)
            if len(ap) >= 3:
                poly = [(int(p[0][0]), int(p[0][1])) for p in ap]
        cands.append((area, Region(x, y, w, h, poly, "auto", area)))

    if not cands:
        return []
    biggest = max(a for a, _ in cands)
    thr = max(min_abs_ratio * H * W, min_rel_area * biggest)
    kept = [r for a, r in cands if a >= thr]
    kept.sort(key=lambda r: -r.area)
    kept = kept[:max_regions]
    band = max(1.0, H / 6.0)
    kept.sort(key=lambda r: (round((r.y + r.h / 2) / band), r.x))
    return kept
