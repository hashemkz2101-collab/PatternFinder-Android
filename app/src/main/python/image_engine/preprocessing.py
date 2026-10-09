"""بارگذاری تصویر و آماده‌سازی (باینری‌سازی) برای تحلیل هندسی.

اصل کار: رنگ و بافت حذف می‌شود و «طرح» به‌صورت ماسک سفید روی زمینهٔ سیاه
برمی‌گردد. چون یک روش واحد برای همهٔ تصاویر جواب نمی‌دهد، چند روش داریم و
حالت «auto» بر اساس آمار تصویر یکی را انتخاب می‌کند.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

import config


class ImageLoadError(Exception):
    """فایل خراب، خالی یا با فرمت پشتیبانی‌نشده."""


# --------------------------------------------------------------------------- #
# بارگذاری
# --------------------------------------------------------------------------- #
def _to_bgr8(img: np.ndarray) -> np.ndarray:
    if img.dtype == np.uint16:
        img = (img / 257.0).astype(np.uint8)
    elif img.dtype != np.uint8:
        img = np.clip(img.astype(np.float32), 0, 255).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 2:  # gray + alpha
        g, a = img[..., 0], img[..., 1].astype(np.float32) / 255.0
        g = (g * a + 255 * (1 - a)).astype(np.uint8)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:  # روی زمینهٔ سفید ترکیب می‌کنیم
        a = img[..., 3:4].astype(np.float32) / 255.0
        rgb = img[..., :3].astype(np.float32)
        return (rgb * a + 255.0 * (1 - a)).astype(np.uint8)
    return img


def _load_with_pillow(path: str) -> np.ndarray | None:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im.seek(0)
            arr = np.array(im.convert("RGBA"))
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
    except Exception:
        return None


def load_image(path: str | Path) -> np.ndarray:
    """تصویر را به‌صورت BGR/uint8 می‌خواند (مسیر فارسی/یونیکد هم امن است)."""
    p = str(path)
    try:
        data = np.fromfile(p, dtype=np.uint8)
    except OSError as exc:
        raise ImageLoadError(f"خواندن فایل ممکن نیست: {exc}") from exc
    if data.size == 0:
        raise ImageLoadError("فایل خالی است")
    img = None
    try:
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except cv2.error:
        img = None
    if img is None:
        img = _load_with_pillow(p)
    if img is None:
        raise ImageLoadError("فایل خراب است یا فرمت آن پشتیبانی نمی‌شود")
    img = _to_bgr8(img)
    h, w = img.shape[:2]
    if h < 16 or w < 16:
        raise ImageLoadError("ابعاد تصویر بسیار کوچک است")
    return img


def to_working(img: np.ndarray, max_side: int | None = None) -> tuple[np.ndarray, float]:
    """کوچک‌کردن تصویر بزرگ تا حداکثر ضلع مشخص. خروجی: (تصویر، ضریب مقیاس)."""
    max_side = max_side or config.PROCESS_MAX_SIDE
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img, 1.0
    s = max_side / float(m)
    out = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    return out, s


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def file_sha1(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# ابزارهای باینری‌سازی
# --------------------------------------------------------------------------- #
def _odd(n: float) -> int:
    n = int(max(3, round(n)))
    return n if n % 2 == 1 else n + 1


def border_light_fraction(gray: np.ndarray) -> float:
    """چند درصد از حاشیهٔ تصویر «روشن» است؟ (برای تشخیص زمینهٔ روشن/تیره)"""
    h, w = gray.shape
    t = max(2, min(h, w) // 100)
    border = np.concatenate(
        [gray[:t].ravel(), gray[-t:].ravel(), gray[:, :t].ravel(), gray[:, -t:].ravel()]
    )
    thr, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float((border > thr).mean())


def _estimate_paper(gray: np.ndarray) -> np.ndarray | None:
    """برآورد روشنایی زمینه (کاغذ) با برازش سطح درجه‌دو و حذف تکرارشوندهٔ نقاط دورافتاده.

    بلوک‌هایی که داخل طرح پُر هستند «تیره‌تر از سطح برازش‌شده» می‌شوند و کنار گذاشته
    می‌شوند؛ بنابراین طرح‌های پُر و بزرگ (حتی کم‌رنگ) توخالی نمی‌شوند.
    """
    h, w = gray.shape
    gh = gw = 24
    if h < gh * 4 or w < gw * 4:
        return None
    bh, bw = h // gh, w // gw
    blocks = gray[: gh * bh, : gw * bw].reshape(gh, bh, gw, bw).transpose(0, 2, 1, 3).reshape(gh, gw, -1)
    grid = np.percentile(blocks, 85, axis=2).astype(np.float64)
    yy, xx = np.mgrid[0:gh, 0:gw]
    x = (xx.ravel() / (gw - 1)) * 2 - 1
    y = (yy.ravel() / (gh - 1)) * 2 - 1
    A = np.column_stack([np.ones_like(x), x, y, x * x, x * y, y * y])
    g = grid.ravel()
    paper = float(np.percentile(g, 90))
    inl = np.ones_like(g, dtype=bool)
    coef = None
    for _ in range(6):
        if inl.sum() < 12:
            return None
        coef, *_ = np.linalg.lstsq(A[inl], g[inl], rcond=None)
        resid = g - A @ coef
        new_inl = resid > -0.06 * paper
        if (new_inl == inl).all():
            break
        inl = new_inl
    fit = (A @ coef).reshape(gh, gw)
    fit = np.clip(fit, 0.5 * paper, 1.3 * paper).astype(np.float32)
    return cv2.resize(fit, (w, h), interpolation=cv2.INTER_CUBIC)


def _flatten(gray: np.ndarray) -> np.ndarray:
    """حذف شیب روشنایی (اسکن‌های ناهمگن)."""
    bg = _estimate_paper(gray)
    if bg is None:
        return gray
    flat = np.clip(gray.astype(np.float32) / np.maximum(bg, 1.0) * 235.0, 0, 255)
    return flat.astype(np.uint8)


def _remove_small(binary: np.ndarray, min_ratio: float) -> np.ndarray:
    min_area = max(6, int(min_ratio * binary.size))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return (keep[lab].astype(np.uint8)) * 255


def _otsu_inv(g: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _mode_otsu(g: np.ndarray) -> np.ndarray:
    return _remove_small(_otsu_inv(cv2.GaussianBlur(g, (3, 3), 0)), 0.00015)


def _mode_scan(g: np.ndarray) -> np.ndarray:
    flat = _flatten(g)
    return _remove_small(_otsu_inv(cv2.GaussianBlur(flat, (3, 3), 0)), 0.0003)


def _mode_adaptive(g: np.ndarray) -> np.ndarray:
    h, w = g.shape
    gb = cv2.GaussianBlur(g, (3, 3), 0)
    b = cv2.adaptiveThreshold(
        gb, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, _odd(min(h, w) / 20), 7
    )
    return _remove_small(b, 0.0002)


def _remove_small_relative(binary: np.ndarray, rel: float, abs_ratio: float) -> np.ndarray:
    """حذف لکه‌های کوچک نسبت به بزرگ‌ترین جزء (برای تصاویر نویزی/بافت‌دار)."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    areas = stats[1:, cv2.CC_STAT_AREA]
    thr = max(6.0, rel * float(areas.max()), abs_ratio * binary.size)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = areas >= thr
    return (keep[lab].astype(np.uint8)) * 255


def _texture_sigma(gray: np.ndarray) -> float:
    """دورهٔ بافت تکراری (مثل پارچه) را با FFT برآورد و سیگمای مناسب محو‌سازی را برمی‌گرداند."""
    h, w = gray.shape
    s = min(256, h, w)
    y0, x0 = (h - s) // 2, (w - s) // 2
    c = gray[y0:y0 + s, x0:x0 + s].astype(np.float32)
    c = c - c.mean()
    win = np.outer(np.hanning(s), np.hanning(s)).astype(np.float32)
    mag = np.abs(np.fft.fftshift(np.fft.fft2(c * win)))
    yy, xx = np.indices(mag.shape)
    rr = np.hypot(yy - s / 2, xx - s / 2).astype(int).ravel()
    pk = np.zeros(rr.max() + 1)
    np.maximum.at(pk, rr, mag.ravel())          # بیشینهٔ هر حلقه (قلهٔ بافت در چند زاویه است)
    lo, hi = max(3, s // 48), s // 3            # دورهٔ ≈ ۳ تا ۴۸ پیکسل
    if hi <= lo + 6:
        return 2.0
    seg = np.log1p(pk[lo:hi])
    padded = np.pad(seg, 4, mode="edge")
    base = np.median(np.lib.stride_tricks.sliding_window_view(padded, 9), axis=1)
    prom = seg - base
    k = int(np.argmax(prom))
    if prom[k] > 0.9:
        period = s / float(lo + k)
        return float(np.clip(period / 4.0, 1.5, 4.5))
    return 2.0


def _mode_faint(g: np.ndarray) -> np.ndarray:
    flat = _flatten(g)
    lo, hi = np.percentile(flat, (0.5, 99.5))
    st = np.clip((flat.astype(np.float32) - lo) * 255.0 / max(1.0, hi - lo), 0, 255).astype(np.uint8)
    st = cv2.GaussianBlur(st, (0, 0), 1.3)
    b = _otsu_inv(st)
    if not _sane(b):  # خطوط خیلی ظریف: آستانهٔ محلی
        b = _mode_adaptive(g)
    return _remove_small_relative(b, 0.004, 0.0003)


def _mode_texture(g: np.ndarray) -> np.ndarray:
    flat = _flatten(g)
    sigma = _texture_sigma(flat)
    sm = cv2.GaussianBlur(flat, (0, 0), sigma)
    b = _otsu_inv(sm)
    b = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return _remove_small_relative(b, 0.06, 0.0008)


_MODE_FUNCS = {
    "otsu": _mode_otsu,
    "scan": _mode_scan,
    "adaptive": _mode_adaptive,
    "faint": _mode_faint,
    "texture": _mode_texture,
}


def describe_gray(gray: np.ndarray) -> dict:
    """آمار ساده‌ای که برای انتخاب خودکار روش استفاده می‌شود."""
    extreme = float(((gray < 40) | (gray > 215)).mean())
    spread = float(np.percentile(gray, 95) - np.percentile(gray, 5))
    edge_density = float(cv2.Canny(gray, 50, 150).mean() / 255.0)
    return {"extreme": extreme, "spread": spread, "edge_density": edge_density}


def choose_mode(gray: np.ndarray) -> str:
    st = describe_gray(gray)
    if st["extreme"] > 0.92:
        return "otsu"
    if st["spread"] < 70:
        return "faint"
    if st["edge_density"] > 0.07:
        return "texture"
    return "scan"


def _sane(binary: np.ndarray) -> bool:
    frac = float((binary > 0).mean())
    return 0.002 <= frac <= 0.65


def orient_dark_ink(gray: np.ndarray, polarity: str = "auto") -> np.ndarray:
    """گرایش را طوری می‌کند که طرح «تیره» و زمینه «روشن» باشد."""
    if polarity == "light_on_dark":
        return 255 - gray
    if polarity == "dark_on_light":
        return gray
    return gray if border_light_fraction(gray) >= 0.5 else 255 - gray


def binarize(gray: np.ndarray, mode: str = "auto", polarity: str = "auto") -> tuple[np.ndarray, str]:
    """خروجی: (ماسک ۰/۲۵۵ با طرح سفید، نام روش استفاده‌شده)."""
    g = orient_dark_ink(gray, polarity)
    if mode in _MODE_FUNCS:
        return _MODE_FUNCS[mode](g), mode
    first = choose_mode(g)
    order = [first] + [m for m in ("scan", "otsu", "adaptive", "texture") if m != first]
    best, best_mode = None, first
    for m in order:
        b = _MODE_FUNCS[m](g)
        if best is None:
            best, best_mode = b, m
        if _sane(b):
            return b, m
    return best, best_mode  # type: ignore[return-value]
