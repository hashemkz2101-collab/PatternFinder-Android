"""استخراج ویژگی‌های هندسی از ماسک یک قطعه.

همهٔ توصیف‌گرهای برداری عمداً نسبت به «چرخش، تغییر اندازه و جابه‌جایی» ناوردا هستند:

* shape  : توصیف‌گر فوریهٔ کانتور (+ ممان‌های Hu)         -> شکل و کانتور
* geom   : نسبت‌ها، سوراخ‌ها، گوشه‌ها، تقارن، تکرار       -> تناسبات و ساختار هندسی
* layout : توزیع شعاعی/زاویه‌ای جرم + آرایش اجزا           -> چیدمان
* lines  : هیستوگرام جهت خطوط (هم‌تراز با جهت غالب)       -> خطوط
* orb    : نقاط کلیدی ORB برای تطبیق محلی و تعیین محل      -> ویژگی‌های محلی
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

import config

FD_HARMONICS = 16
FD_POINTS = 128
HU_USED = 4
SHAPE_DIM = FD_HARMONICS * 2 + HU_USED          # 36
GEOM_DIM = 24
RINGS, SECTORS = 6, 12
LAYOUT_DIM = RINGS * (SECTORS // 2 + 1) + 12    # 54
LINES_BINS = 18
LINES_DIM = LINES_BINS + 2                      # 20
ORB_PAD = 40
MIN_AREA_PIXELS = 30


@dataclass
class Features:
    shape: np.ndarray
    geom: np.ndarray
    layout: np.ndarray
    lines: np.ndarray
    bbox: tuple                                  # (x, y, w, h) در تصویر کاری
    orb_des: np.ndarray = field(default_factory=lambda: np.zeros((0, 32), np.uint8))
    orb_pts: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), np.float32))
    orb_scale: float = 1.0                       # پیکسل نرمال به ازای هر پیکسل تصویر کاری
    area: int = 0

    # --- ذخیره/بازیابی --------------------------------------------------- #
    def to_row(self) -> tuple:
        return (
            self.shape.astype(np.float32).tobytes(),
            self.geom.astype(np.float32).tobytes(),
            self.layout.astype(np.float32).tobytes(),
            self.lines.astype(np.float32).tobytes(),
            int(len(self.orb_des)),
            float(self.orb_scale),
            np.ascontiguousarray(self.orb_des, np.uint8).tobytes(),
            np.ascontiguousarray(self.orb_pts, np.float32).tobytes(),
        )


def unpack_orb(des_blob, pts_blob, n: int) -> tuple[np.ndarray, np.ndarray]:
    if not n or not des_blob:
        return np.zeros((0, 32), np.uint8), np.zeros((0, 2), np.float32)
    des = np.frombuffer(des_blob, np.uint8).reshape(n, 32)
    pts = np.frombuffer(pts_blob, np.float32).reshape(n, 2)
    return des, pts


# --------------------------------------------------------------------------- #
# ابزارهای کمکی
# --------------------------------------------------------------------------- #
def _tight_crop(mask: np.ndarray) -> Optional[tuple[np.ndarray, int, int]]:
    pts = cv2.findNonZero(mask)
    if pts is None:
        return None
    x, y, w, h = cv2.boundingRect(pts)
    return mask[y:y + h, x:x + w], x, y


def _resize_mask(crop: np.ndarray, target: int) -> tuple[np.ndarray, float]:
    h, w = crop.shape[:2]
    s = target / float(max(h, w))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    r = cv2.resize(crop, (nw, nh), interpolation=interp)
    return ((r > 48).astype(np.uint8)) * 255, s


def _ellipse(k: int) -> np.ndarray:
    k = max(3, k | 1)
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def _main_contour(m: np.ndarray) -> Optional[np.ndarray]:
    """بزرگ‌ترین کانتور بیرونی بعد از چسباندن شکاف‌های ریز."""
    joined = cv2.dilate(m, _ellipse(5))
    cs, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if len(c) < 8:
        return None
    return c.reshape(-1, 2).astype(np.float64)


def _resample_closed(pts: np.ndarray, n: int) -> Optional[np.ndarray]:
    closed = np.vstack([pts, pts[:1]])
    d = np.hypot(*np.diff(closed, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(d)])
    if s[-1] < 1e-6:
        return None
    t = np.linspace(0, s[-1], n, endpoint=False)
    x = np.interp(t, s, closed[:, 0])
    y = np.interp(t, s, closed[:, 1])
    return x + 1j * y


# --------------------------------------------------------------------------- #
# شکل
# --------------------------------------------------------------------------- #
def _shape_vector(m: np.ndarray, contour: np.ndarray) -> Optional[np.ndarray]:
    z = _resample_closed(contour, FD_POINTS)
    if z is None:
        return None
    z = z - z.mean()
    Z = np.fft.fft(z) / FD_POINTS
    pos = np.abs(Z[1:FD_HARMONICS + 1])
    neg = np.abs(Z[-1:-FD_HARMONICS - 1:-1])
    energy = math.sqrt(float(np.sum(np.abs(Z[1:]) ** 2))) + 1e-9
    a, b = pos / energy, neg / energy
    # جمع و قدرمطلق تفاضل: نسبت به جهت پیمایش کانتور (و آینه) ناوردا
    fd = np.concatenate([np.sqrt(a + b), np.sqrt(np.abs(a - b))])

    mom = cv2.moments(m, binaryImage=True)
    hu = cv2.HuMoments(mom).ravel()
    hu = -np.sign(hu) * np.log10(np.abs(hu) + 1e-30)
    hu = np.clip(hu[:HU_USED], 0.0, 12.0) * 0.1
    return np.concatenate([fd, hu]).astype(np.float32)


# --------------------------------------------------------------------------- #
# هندسه
# --------------------------------------------------------------------------- #
def _soft_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = np.minimum(a, b).sum()
    union = np.maximum(a, b).sum()
    return float(inter / union) if union > 0 else 0.0


def _symmetry(m: np.ndarray, cx: float, cy: float, R: float) -> list[float]:
    # نیم‌اندازه: سرعت ۴ برابر، با دقت کافی برای سنجش تقارن
    m = cv2.resize(m, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    cx, cy, R = cx * 0.5, cy * 0.5, R * 0.5
    S = int(2 * math.ceil(R)) + 8
    base = np.float32(255)
    shift = np.array([[1, 0, S / 2 - cx], [0, 1, S / 2 - cy]], np.float32)
    canvas = cv2.warpAffine(m, shift, (S, S), flags=cv2.INTER_LINEAR)
    canvas = cv2.GaussianBlur(canvas, (0, 0), 1.0).astype(np.float32) / base
    c = (S / 2.0, S / 2.0)

    def rot(img, ang):
        M = cv2.getRotationMatrix2D(c, ang, 1.0)
        return cv2.warpAffine(img, M, (S, S), flags=cv2.INTER_LINEAR)

    mirror_scores = []
    for ang in range(0, 180, 10):
        r = rot(canvas, ang)
        mirror_scores.append(_soft_iou(r, r[:, ::-1]))
    ms = np.array(mirror_scores)
    out = [float(ms.max()), float((ms > 0.9).sum()) / len(ms)]
    for n in (2, 3, 4, 5, 6):
        out.append(_soft_iou(canvas, rot(canvas, 360.0 / n)))
    return out


def _geom_vector(m: np.ndarray, contour: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    area = float(len(xs))
    cx, cy = float(xs.mean()), float(ys.mean())
    dx, dy = xs - cx, ys - cy
    r = np.hypot(dx, dy)
    R = float(r.max()) + 1e-6

    pts = np.column_stack([xs, ys]).astype(np.float32)
    (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
    long_, short_ = max(rw, rh, 1.0), max(min(rw, rh), 1.0)
    aspect = short_ / long_
    extent = min(1.0, area / (long_ * short_))
    hull = cv2.convexHull(pts)
    hull_area = max(cv2.contourArea(hull), 1.0)
    solidity = min(1.0, area / hull_area)
    peri = max(cv2.arcLength(contour.astype(np.float32).reshape(-1, 1, 2), True), 1.0)
    cont_area = max(cv2.contourArea(contour.astype(np.float32).reshape(-1, 1, 2)), 1.0)
    circ = min(1.0, 4 * math.pi * cont_area / (peri * peri))

    cs, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    holes, hole_area, parts = 0, 0.0, 0
    if hier is not None:
        for c, hh in zip(cs, hier[0]):
            a = cv2.contourArea(c)
            if hh[3] != -1:
                if a >= 0.002 * area:
                    holes += 1
                    hole_area += a
            elif a >= 0.005 * area:
                parts += 1
    hole_ratio = min(1.0, hole_area / max(area + hole_area, 1.0))

    ap = cv2.approxPolyDP(contour.astype(np.float32).reshape(-1, 1, 2), 0.015 * peri, True)
    corners = len(ap)

    sym = _symmetry(m, cx, cy, R)

    theta = np.arctan2(dy, dx)
    sec = np.minimum(((theta + math.pi) / (2 * math.pi) * 36).astype(int), 35)
    prof = np.bincount(sec, minlength=36).astype(np.float64)
    harm = np.abs(np.fft.rfft(prof))[1:9] / max(prof.sum(), 1.0)
    fill = min(1.0, area / (math.pi * R * R))

    v = [aspect, extent, solidity, circ,
         math.log1p(holes) / 2.5, hole_ratio, math.log1p(parts) / 2.5, math.log1p(corners) / 3.5]
    v += sym                       # 7
    v += list(harm * 2.0)          # 8
    v.append(fill)
    return np.array(v, np.float32)


# --------------------------------------------------------------------------- #
# چیدمان
# --------------------------------------------------------------------------- #
def _layout_vector(m: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
    n = float(len(xs))
    cx, cy = xs.mean(), ys.mean()
    dx, dy = xs - cx, ys - cy
    r = np.hypot(dx, dy)
    R = float(r.max()) + 1e-6
    ring = np.minimum((RINGS * (r / R) ** 2).astype(int), RINGS - 1)
    sec = np.minimum(((np.arctan2(dy, dx) + math.pi) / (2 * math.pi) * SECTORS).astype(int), SECTORS - 1)
    occ = np.bincount(ring * SECTORS + sec, minlength=RINGS * SECTORS).reshape(RINGS, SECTORS) / n
    spec = np.abs(np.fft.rfft(occ, axis=1))
    polar = np.sqrt(spec).ravel()

    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    items = []
    for c in cs:
        a = cv2.contourArea(c)
        if a < 0.005 * n:
            continue
        mo = cv2.moments(c)
        if mo["m00"] <= 0:
            continue
        px, py = mo["m10"] / mo["m00"], mo["m01"] / mo["m00"]
        items.append((a / n, math.hypot(px - cx, py - cy) / R))
    items.sort(key=lambda t: -t[0])
    arr = np.zeros(12, np.float32)
    for i, (ar, dist) in enumerate(items[:6]):
        arr[2 * i] = ar
        arr[2 * i + 1] = dist
    return np.concatenate([polar, arr]).astype(np.float32)


# --------------------------------------------------------------------------- #
# خطوط
# --------------------------------------------------------------------------- #
def _lines_vector(m: np.ndarray) -> np.ndarray:
    size = max(m.shape)
    edges = cv2.morphologyEx(m, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    perim = max(float(np.count_nonzero(edges)) / 2.0, 1.0)
    segs = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=18,
                           minLineLength=max(14, int(0.10 * size)), maxLineGap=4)
    hist = np.zeros(LINES_BINS, np.float64)
    total = 0.0
    n_lines = 0
    if segs is not None:
        for x1, y1, x2, y2 in segs[:, 0, :]:
            L = math.hypot(x2 - x1, y2 - y1)
            ang = math.atan2(y2 - y1, x2 - x1) % math.pi
            b = min(int(ang / math.pi * LINES_BINS), LINES_BINS - 1)
            hist[b] += L
            total += L
            n_lines += 1
    out = np.zeros(LINES_DIM, np.float32)
    if total > 0:
        hist = hist / total
        k = np.array([0.25, 0.5, 0.25])
        hist = sum(w * np.roll(hist, s) for w, s in zip(k, (-1, 0, 1)))
        hist = np.roll(hist, -int(np.argmax(hist)))   # هم‌ترازی با جهت غالب
        out[:LINES_BINS] = hist
        out[LINES_BINS] = min(1.0, total / perim)
        out[LINES_BINS + 1] = math.log1p(n_lines) / 3.0
    return out


# --------------------------------------------------------------------------- #
# ORB
# --------------------------------------------------------------------------- #
def _orb_features(crop: np.ndarray, size: int, n_features: int):
    """نقاط کلیدی ORB روی نسخهٔ نرمال‌شدهٔ ماسک. مختصات: فضای نرمال (گوشهٔ بالا-چپ قطعه = ۰)."""
    img, s = _resize_mask(crop, size)
    padded = cv2.copyMakeBorder(img, ORB_PAD, ORB_PAD, ORB_PAD, ORB_PAD, cv2.BORDER_CONSTANT, value=0)
    padded = cv2.GaussianBlur(padded, (0, 0), 2.0)
    orb = cv2.ORB_create(nfeatures=n_features, scaleFactor=1.2, nlevels=8,
                         edgeThreshold=31, patchSize=31, fastThreshold=5)
    kps, des = orb.detectAndCompute(padded, None)
    if des is None or len(kps) < 4:
        return np.zeros((0, 32), np.uint8), np.zeros((0, 2), np.float32), s
    pts = np.array([[k.pt[0] - ORB_PAD, k.pt[1] - ORB_PAD] for k in kps], np.float32)
    return des.astype(np.uint8), pts, s


# --------------------------------------------------------------------------- #
# نقطهٔ ورود
# --------------------------------------------------------------------------- #
def compute_features(
    mask: np.ndarray,
    origin: tuple[int, int] = (0, 0),
    kind: str = "part",
    with_orb: bool = True,
) -> Optional[Features]:
    """mask: ماسک ۰/۲۵۵ (طرح سفید). origin: مختصات گوشهٔ بالا-چپ ماسک در تصویر کاری."""
    if mask is None or mask.size == 0:
        return None
    tc = _tight_crop(mask)
    if tc is None:
        return None
    crop, bx, by = tc
    if int(cv2.countNonZero(crop)) < MIN_AREA_PIXELS:
        return None

    m, _ = _resize_mask(crop, config.NORM_SIZE)
    m = cv2.copyMakeBorder(m, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=0)
    ys, xs = np.nonzero(m)
    if len(xs) < MIN_AREA_PIXELS:
        return None
    contour = _main_contour(m)
    if contour is None:
        return None
    shape = _shape_vector(m, contour)
    if shape is None:
        return None
    geom = _geom_vector(m, contour, ys, xs)
    layout = _layout_vector(m, ys, xs)
    lines = _lines_vector(m)

    des = np.zeros((0, 32), np.uint8)
    pts = np.zeros((0, 2), np.float32)
    s_orb = 1.0
    if with_orb:
        size = config.ORB_SIZE_WHOLE if kind == "whole" else config.ORB_SIZE_PART
        nf = config.ORB_FEATURES_WHOLE if kind == "whole" else config.ORB_FEATURES_PART
        des, pts, s_orb = _orb_features(crop, size, nf)

    ox, oy = origin
    return Features(
        shape=shape, geom=geom, layout=layout, lines=lines,
        bbox=(int(ox + bx), int(oy + by), int(crop.shape[1]), int(crop.shape[0])),
        orb_des=des, orb_pts=pts, orb_scale=float(s_orb), area=int(cv2.countNonZero(crop)),
    )
