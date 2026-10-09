"""تولید داده‌های مصنوعی برای آزمایش خودکار موتور (بدون نیاز به تصاویر واقعی)."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


# --------------------------------------------------------------------------- #
# شکل‌ها
# --------------------------------------------------------------------------- #
def _polar_points(radii: np.ndarray, R: float, c: float) -> np.ndarray:
    n = len(radii)
    th = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([c + R * radii * np.cos(th), c + R * radii * np.sin(th)])


def make_shape(seed: int, size: int = 256) -> np.ndarray:
    """یک طرح تصادفی ولی قابل‌تکرار (بر اساس seed). خروجی: ماسک ۰/۲۵۵."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size), np.uint8)
    c = size / 2.0
    R = size * 0.42
    kind = rng.choice(["fourier", "fourier", "fourier", "fourier", "star", "rosette", "poly", "gear"])
    th = np.linspace(0, 2 * math.pi, 360, endpoint=False)
    if kind == "fourier":
        r = np.ones_like(th)
        ks = rng.choice(np.arange(2, 8), size=int(rng.integers(2, 5)), replace=False)
        for k in ks:
            r += rng.uniform(0.12, 0.38) * np.cos(k * th + rng.uniform(0, 2 * math.pi))
        r = np.clip(r, 0.25, None)
        r /= r.max()
        pts = _polar_points(r, R, c)
    elif kind == "star":
        n = int(rng.integers(4, 10))
        inner = rng.uniform(0.3, 0.62)
        r = np.array([1.0 if i % 2 == 0 else inner for i in range(2 * n)])
        pts = _polar_points(r, R, c)
    elif kind == "rosette":
        n = int(rng.integers(3, 9))
        r = 0.45 + 0.55 * np.abs(np.cos(n * th / 2.0))
        pts = _polar_points(r, R, c)
    elif kind == "poly":
        m = int(rng.integers(3, 9))
        r = rng.uniform(0.62, 1.0, size=m)
        r[int(rng.integers(0, m))] = 1.0
        pts = _polar_points(r, R, c)
    else:  # gear
        t = int(rng.integers(6, 15))
        base = np.array([1.0, 1.0, 0.72, 0.72] * t)
        pts = _polar_points(base, R, c)

    outline = rng.random() < 0.45
    p32 = np.round(pts).astype(np.int32)
    if outline:
        cv2.polylines(img, [p32], True, 255, int(rng.integers(4, 9)), cv2.LINE_AA)
        if rng.random() < 0.5:
            inner_pts = np.round((pts - c) * rng.uniform(0.4, 0.6) + c).astype(np.int32)
            cv2.polylines(img, [inner_pts], True, 255, 4, cv2.LINE_AA)
    else:
        cv2.fillPoly(img, [p32], 255, cv2.LINE_AA)
        if rng.random() < 0.5:  # سوراخ‌ها
            for _ in range(int(rng.integers(1, 4))):
                a = rng.uniform(0, 2 * math.pi)
                d = rng.uniform(0, 0.4) * R
                cv2.circle(img, (int(c + d * math.cos(a)), int(c + d * math.sin(a))),
                           int(rng.uniform(0.06, 0.14) * R), 0, -1, cv2.LINE_AA)
    return ((img > 100).astype(np.uint8)) * 255


def transform_mask(mask: np.ndarray, angle: float, scale: float, out_size: int | None = None,
                   center: tuple[float, float] | None = None) -> np.ndarray:
    h, w = mask.shape
    out_size = out_size or int(max(h, w) * max(1.0, scale) * 1.5)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    cx, cy = center if center else (out_size / 2, out_size / 2)
    M[0, 2] += cx - w / 2
    M[1, 2] += cy - h / 2
    out = cv2.warpAffine(mask, M, (out_size, out_size), flags=cv2.INTER_LINEAR)
    return ((out > 100).astype(np.uint8)) * 255


# --------------------------------------------------------------------------- #
# سبک تصویر: تمیز / اسکن / بافت‌دار
# --------------------------------------------------------------------------- #
def stylize(mask: np.ndarray, style: str, rng: np.random.Generator) -> np.ndarray:
    """ماسک (طرح سفید) را به یک تصویر BGR شبیه واقعیت تبدیل می‌کند."""
    h, w = mask.shape
    m = mask.astype(np.float32) / 255.0
    if style == "clean":
        g = (1 - m) * 255
        return cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if style == "scan":
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        grad = 1.0 - 0.22 * (xx / w) - 0.12 * (yy / h)            # سایهٔ ناهمگن
        ink = rng.uniform(25, 70)
        g = (235 * (1 - m) + ink * m) * grad
        g += rng.normal(0, 5, g.shape)
        g = cv2.GaussianBlur(g, (0, 0), 0.9)
        g = np.clip(g, 0, 255).astype(np.uint8)
        _, enc = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(45, 75))])
        return cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE), cv2.COLOR_GRAY2BGR)
    if style == "faint":
        g = 238 * (1 - m) + 175 * m
        g += rng.normal(0, 3, g.shape)
        return cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    # بافت پارچه‌ای رنگی
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    f = rng.uniform(0.35, 0.6)
    weave = 0.5 + 0.25 * np.sin(xx * f) * np.sin(yy * f)
    noise = cv2.GaussianBlur(rng.normal(0.0, 1.0, (h, w)).astype(np.float32), (0, 0), 1.2) * 0.18
    base = np.clip(weave + noise, 0, 1)
    bg = np.dstack([base * c for c in rng.uniform(180, 235, 3)])
    ink = np.dstack([(0.45 + 0.4 * base) * c for c in rng.uniform(15, 80, 3)])
    soft = cv2.GaussianBlur(m, (0, 0), 0.8)[..., None]
    out = bg * (1 - soft) + ink * soft
    return np.clip(out, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# ساخت کتابخانه و پرسش‌ها
# --------------------------------------------------------------------------- #
def make_library(folder: Path, n_images: int = 40, seed: int = 0,
                 styles=("clean", "clean", "scan", "texture", "faint"), canvas: int = 640):
    """n_images تصویر با ۱ تا ۳ قطعه. خروجی: لیست دیکشنری‌ها با فیلد parts (شناسهٔ شکل‌ها)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    slots = {
        1: [(0.5, 0.5, 0.80)],
        2: [(0.28, 0.5, 0.50), (0.74, 0.5, 0.50)],
        3: [(0.27, 0.27, 0.42), (0.73, 0.30, 0.42), (0.5, 0.74, 0.46)],
    }
    out = []
    shape_id = seed * 100000
    for i in range(n_images):
        k = int(rng.choice([1, 2, 3], p=[0.4, 0.35, 0.25]))
        page = np.zeros((canvas, canvas), np.uint8)
        parts = []
        for (fx, fy, fs) in slots[k]:
            shape_id += 1
            base = make_shape(shape_id)
            ang = float(rng.uniform(0, 360))
            sc = fs * canvas / 256.0 * 0.95
            t = transform_mask(base, ang, sc, canvas, (fx * canvas, fy * canvas))
            page |= t
            parts.append({"shape_id": shape_id, "angle": ang, "scale": sc, "center": (fx, fy)})
        style = str(rng.choice(list(styles)))
        img = stylize(page, style, rng)
        path = folder / f"lib_{i:04d}_{style}.png"
        cv2.imencode(".png", img)[1].tofile(str(path))
        out.append({"path": str(path), "parts": parts, "style": style, "index": i})
    return out


def make_query(shape_id: int, path: Path, style: str, seed: int, size: int = 480):
    """قطعهٔ shape_id با چرخش/اندازهٔ تصادفی و سبک دلخواه."""
    rng = np.random.default_rng(seed)
    base = make_shape(shape_id)
    ang = float(rng.uniform(0, 360))
    sc = float(rng.uniform(0.55, 1.5))
    m = transform_mask(base, ang, sc * size / 256.0 * 0.55, size)
    img = stylize(m, style, rng)
    cv2.imencode(".png", img)[1].tofile(str(path))
    return {"angle": ang, "scale": sc}
