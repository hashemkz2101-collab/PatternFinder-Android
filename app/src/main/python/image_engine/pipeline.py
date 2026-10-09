"""زنجیرهٔ کامل: بارگذاری -> باینری‌سازی -> تشخیص قطعات -> ویژگی‌ها."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

import config
from image_engine import preprocessing as pre
from image_engine import segmentation as seg
from image_engine.geometry_features import Features, compute_features
from image_engine.segmentation import Region


@dataclass
class Analysis:
    path: str
    image: np.ndarray          # BGR، اندازهٔ تصویر کاری
    binary: np.ndarray         # ۰/۲۵۵ طرح سفید
    mode_used: str
    scale: float               # اصلی -> کاری
    regions: list

    @property
    def size(self) -> tuple[int, int]:
        h, w = self.binary.shape[:2]
        return w, h


def analyze_image(
    path: str | Path,
    mode: str = "auto",
    polarity: str = "auto",
    regions: Optional[list] = None,
    max_side: Optional[int] = None,
) -> Analysis:
    """regions=None یعنی تشخیص خودکار قطعات."""
    img = pre.load_image(path)
    work, scale = pre.to_working(img, max_side)
    gray = pre.to_gray(work)
    binary, used = pre.binarize(gray, mode, polarity)
    if regions is None:
        regions = seg.detect_regions(binary)
    return Analysis(str(path), work, binary, used, scale, regions)


def region_features(binary: np.ndarray, region: Region, with_orb: bool = True) -> Optional[Features]:
    res = seg.mask_from_region(binary, region)
    if res is None:
        return None
    mask, origin = res
    return compute_features(mask, origin, "part", with_orb)


def whole_features(binary: np.ndarray, regions: list, with_orb: bool = True) -> Optional[Features]:
    res = seg.union_mask(binary, regions)
    if res is None:
        return None
    mask, origin = res
    return compute_features(mask, origin, "whole", with_orb)


def default_query_region(an: Analysis) -> Optional[Region]:
    """اگر کاربر چیزی انتخاب نکرده، بزرگ‌ترین قطعه."""
    if not an.regions:
        return None
    return max(an.regions, key=lambda r: r.area or r.w * r.h)
