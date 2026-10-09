"""پل بین رابط Kotlin و موتور PatternFinder.

همهٔ توابع عمومی، رشتهٔ JSON (یا مقدار ساده) برمی‌گردانند تا Kotlin بدون وابستگی به نوع‌های پایتون کار کند.
مختصات همه‌جا در «تصویر کاری» (حداکثر ضلع config.PROCESS_MAX_SIDE) است؛ دقیقاً مثل نسخهٔ ویندوز.
"""
from __future__ import annotations

import dataclasses
import glob
import json
import logging
import os
import shutil
import tempfile
import traceback
from logging.handlers import RotatingFileHandler

import cv2
import numpy as np

_S: dict = {"seq": 0, "cancel": False}
log = logging.getLogger("patternfinder")


# --------------------------------------------------------------------------- #
# راه‌اندازی
# --------------------------------------------------------------------------- #
def init(data_dir: str) -> str:
    os.makedirs(data_dir, exist_ok=True)
    os.environ["PATTERNFINDER_DATA"] = data_dir
    import config
    from database.repository import Repository
    from image_engine.matching import LibraryIndex

    log.setLevel(logging.INFO)
    try:
        h = RotatingFileHandler(str(config.LOG_DIR / "patternfinder.log"), maxBytes=1_000_000,
                                backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        pass

    _S["config"] = config
    _S["settings"] = config.Settings.load()
    _S["repo"] = Repository(config.DB_PATH)
    s = _S["settings"]
    _S["index"] = LibraryIndex(_S["repo"], s.deep_scan, _workers())
    _S["cache"] = str(config.CACHE_DIR)
    log.info("bridge init, cv2 %s, numpy %s", cv2.__version__, np.__version__)
    return f"{config.APP_VERSION}|cv2 {cv2.__version__}|numpy {np.__version__}"


def _workers() -> int:
    w = _S["settings"].workers
    if w and w > 0:
        return int(w)
    # روی گوشی: دما و باتری مهم است؛ ۴ نخ پیش‌فرض خوب است
    return max(1, min(4, (os.cpu_count() or 2) - 1))


def _repo():
    return _S["repo"]


def cancel() -> None:
    _S["cancel"] = True


def _begin() -> None:
    _S["cancel"] = False


def _cancelled() -> bool:
    return bool(_S["cancel"])


def _prog(cb):
    if cb is None:
        return None

    def f(i, n, m=""):
        try:
            cb.onProgress(int(i), int(n), str(m))
        except Exception:  # noqa: BLE001  (خطای رابط نباید کار را متوقف کند)
            pass
    return f


# --------------------------------------------------------------------------- #
# برچسب‌ها و تنظیمات
# --------------------------------------------------------------------------- #
def labels() -> str:
    c = _S["config"]
    return json.dumps({
        "modes": [[k, v] for k, v in c.PREPROCESS_MODES.items()],
        "polarities": [[k, v] for k, v in c.POLARITY_MODES.items()],
        "weight_labels": c.WEIGHT_LABELS,
        "default_weights": c.DEFAULT_WEIGHTS,
        "weight_keys": list(c.DEFAULT_WEIGHTS.keys()),
    }, ensure_ascii=False)


def get_settings() -> str:
    s = _S["settings"]
    return json.dumps(dataclasses.asdict(s), ensure_ascii=False)


def save_settings(js: str) -> None:
    s = _S["settings"]
    d = json.loads(js)
    for k, v in d.items():
        if hasattr(s, k):
            setattr(s, k, v)
    s.save()


def _ensure_index(prog=None):
    from image_engine.matching import LibraryIndex
    s = _S["settings"]
    idx = _S["index"]
    if idx.deep_scan != s.deep_scan or idx.workers != _workers():
        idx = LibraryIndex(_repo(), s.deep_scan, _workers())
        _S["index"] = idx
    if idx.is_stale():
        idx.load(prog)
    return idx


# --------------------------------------------------------------------------- #
# ابزارهای کمکی
# --------------------------------------------------------------------------- #
def _regions_json(regs) -> list:
    out = []
    for r in regs:
        out.append({"x": int(r.x), "y": int(r.y), "w": int(r.w), "h": int(r.h),
                    "polygon": [[int(a), int(b)] for a, b in r.polygon] if r.polygon else None,
                    "source": r.source, "area": int(r.area or 0)})
    return out


def _region_from(d: dict):
    from image_engine.segmentation import Region
    poly = d.get("polygon")
    if poly:
        r = Region.from_polygon([(p[0], p[1]) for p in poly], d.get("source", "manual"))
    else:
        r = Region.from_rect(d["x"], d["y"], d["w"], d["h"], d.get("source", "manual"))
    r.area = int(d.get("area", 0) or 0)
    return r


def _regions_from(js: str) -> list:
    return [_region_from(d) for d in json.loads(js or "[]")]


def _next_seq() -> int:
    _S["seq"] += 1
    return _S["seq"]


def _clean(prefix: str) -> None:
    for p in glob.glob(os.path.join(_S["cache"], prefix + "*.jpg")):
        try:
            os.remove(p)
        except OSError:
            pass


def _write_jpg(img_bgr: np.ndarray, name: str, quality: int = 88) -> str:
    p = os.path.join(_S["cache"], name)
    cv2.imwrite(p, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return p


def _previews(an, prefix: str) -> tuple[str, str]:
    _clean(prefix)
    n = _next_seq()
    img = _write_jpg(an.image, f"{prefix}{n}_img.jpg")
    binimg = cv2.bitwise_not(an.binary)          # طرح سیاه روی سفید
    b = _write_jpg(binimg, f"{prefix}{n}_bin.jpg")
    return img, b


# --------------------------------------------------------------------------- #
# کتابخانه
# --------------------------------------------------------------------------- #
def counts() -> str:
    return json.dumps(_repo().count_by_status())


def list_images(status: str = "") -> str:
    rows = _repo().list_images(status or None)
    return json.dumps([{"id": r.id, "path": r.path, "name": os.path.basename(r.path),
                        "status": r.status, "label": r.status_label, "error": r.error or ""}
                       for r in rows], ensure_ascii=False)


def scan(folder: str, cb=None) -> str:
    from database import index_builder as ib
    _begin()
    rep = ib.scan_library(_repo(), folder, _prog(cb), _cancelled, _workers(),
                          _S["settings"].default_mode)
    _S["settings"].last_library = folder
    _S["settings"].save()
    d = dataclasses.asdict(rep)
    d["errors"] = d["errors"][:5]
    d["summary"] = rep.summary()
    return json.dumps(d, ensure_ascii=False)


def approve_all(cb=None) -> int:
    from database import index_builder as ib
    _begin()
    return int(ib.approve_all(_repo(), None, _prog(cb), _cancelled, _workers()))


def load_image(image_id: int) -> str:
    from image_engine import pipeline
    from image_engine import preprocessing as pre
    row = _repo().get_image(image_id)
    d = {"id": image_id, "ok": False, "error": "تصویر در پایگاه داده نیست"}
    if row is None:
        return json.dumps(d, ensure_ascii=False)
    d = {"id": row.id, "path": row.path, "name": os.path.basename(row.path), "status": row.status,
         "label": row.status_label, "error": row.error or "", "ok": False,
         "mode": row.preprocess_mode or "auto", "polarity": row.polarity or "auto",
         "mode_used": "", "preview": "", "binary": "", "width": 0, "height": 0, "regions": []}
    if row.status in ("duplicate", "corrupt"):
        return json.dumps(d, ensure_ascii=False)
    try:
        regs = _repo().get_regions(image_id) or None
        an = pipeline.analyze_image(row.path, d["mode"], d["polarity"], regions=regs)
    except pre.ImageLoadError as exc:
        d["error"] = f"خواندن تصویر ممکن نیست: {exc}"
        return json.dumps(d, ensure_ascii=False)
    img, b = _previews(an, "lib_")
    w, h = an.size
    d.update(ok=True, mode_used=an.mode_used, preview=img, binary=b, width=w, height=h,
             regions=_regions_json(an.regions))
    return json.dumps(d, ensure_ascii=False)


def redetect(image_id: int, mode: str, polarity: str) -> str:
    from database import index_builder as ib
    ib.redetect(_repo(), image_id, mode, polarity)
    return load_image(image_id)


def approve(image_id: int, regions_js: str) -> int:
    from database import index_builder as ib
    return int(ib.approve_image(_repo(), image_id, _regions_from(regions_js)))


def next_pending(after_id: int, status: str = "") -> int:
    pend = [r.id for r in _repo().list_images("pending")]
    if not pend:
        return -1
    ids = [r.id for r in _repo().list_images(status or None)]
    order = ids[ids.index(after_id) + 1:] if after_id in ids else ids
    pend_set = set(pend)
    return next((i for i in order if i in pend_set), pend[0])


# --------------------------------------------------------------------------- #
# جستجو
# --------------------------------------------------------------------------- #
def query_load(path: str, mode: str = "auto", polarity: str = "auto") -> str:
    from image_engine import pipeline
    from image_engine import preprocessing as pre
    try:
        an = pipeline.analyze_image(path, mode, polarity)
    except pre.ImageLoadError as exc:
        return json.dumps({"ok": False, "error": f"تصویر خوانده نشد: {exc}"}, ensure_ascii=False)
    _S["q"] = an
    default = pipeline.default_query_region(an)
    idx = an.regions.index(default) if default is not None else -1
    img, b = _previews(an, "qry_")
    w, h = an.size
    return json.dumps({"ok": True, "preview": img, "binary": b, "width": w, "height": h,
                       "mode": mode, "polarity": polarity, "mode_used": an.mode_used,
                       "default_index": idx, "regions": _regions_json(an.regions)},
                      ensure_ascii=False)


def query_search(region_js: str, regions_js: str, mode: str, cb=None) -> str:
    from image_engine import io_utils, pipeline
    an = _S.get("q")
    if an is None:
        return json.dumps({"error": "no_query", "results": []})
    _begin()
    prog = _prog(cb) or (lambda *a: None)
    region = _region_from(json.loads(region_js)) if region_js else pipeline.default_query_region(an)
    if region is None:
        return json.dumps({"error": "no_region", "results": []})
    feat = pipeline.region_features(an.binary, region)
    if feat is None:
        return json.dumps({"error": "no_pattern", "results": []})
    whole = None
    if mode == "combined":
        regs = _regions_from(regions_js) or an.regions
        whole = pipeline.whole_features(an.binary, regs)
    s = _S["settings"]
    index = _ensure_index(prog)
    res = index.search(feat, whole, mode, s.weights, s.top_k, s.rerank, prog, _cancelled)
    _clean("res_")
    seq = _next_seq()
    out = []
    for i, r in enumerate(res):
        prog(i, len(res), "ساخت پیش‌نمایش نتایج…")
        thumb = ""
        pv = io_utils.make_preview(r.path, r.polygon, 360)
        if pv is not None:
            thumb = _write_jpg(cv2.cvtColor(pv, cv2.COLOR_RGB2BGR), f"res_{seq}_{i}.jpg", 82)
        out.append({
            "image_id": r.image_id, "path": r.path, "name": os.path.basename(r.path),
            "score": float(r.score), "parts": {k: float(v) for k, v in r.parts.items()},
            "component_score": float(r.component_score), "image_score": float(r.image_score),
            "match_type": r.match_type, "label": r.label(),
            "polygon": [[float(a), float(b)] for a, b in (r.polygon or [])], "thumb": thumb,
        })
        if _cancelled():
            break
    n_ok = _repo().count_by_status().get("approved", 0)
    return json.dumps({"error": "", "approved": int(n_ok), "results": out}, ensure_ascii=False)


def result_detail(path: str, polygon_js: str) -> str:
    from image_engine import io_utils
    poly = json.loads(polygon_js or "[]") or None
    pv = io_utils.make_preview(path, poly, 1200)
    if pv is None:
        return ""
    _clean("det_")
    return _write_jpg(cv2.cvtColor(pv, cv2.COLOR_RGB2BGR), f"det_{_next_seq()}.jpg", 90)


# --------------------------------------------------------------------------- #
# عیب‌یابی
# --------------------------------------------------------------------------- #
def selftest() -> str:
    """کتابخانهٔ مصنوعی کوچک می‌سازد و جستجو می‌کند (بررسی سلامت موتور روی همین گوشی)."""
    from database import index_builder as ib
    from database.repository import Repository
    from image_engine import pipeline, ranking
    from image_engine.matching import LibraryIndex
    from tools import synthetic as syn
    from pathlib import Path
    import time

    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="pf_selftest_", dir=_S["cache"]))
    try:
        meta = syn.make_library(tmp / "lib", 12, seed=5, styles=("clean",))
        repo = Repository(tmp / "t.db")
        ib.scan_library(repo, tmp / "lib", workers=2)
        ib.approve_all(repo, workers=2)
        idx = LibraryIndex(repo)
        idx.load()
        pid = {r.path: r.id for r in repo.list_images()}
        sid = meta[2]["parts"][0]["shape_id"]
        q = tmp / "q.png"
        syn.make_query(sid, q, "clean", 3)
        an = pipeline.analyze_image(q)
        f = pipeline.region_features(an.binary, pipeline.default_query_region(an))
        rank = ranking.rank_of(idx.search(f, top_k=10), pid[meta[2]["path"]])
        repo.close()
        ok = rank is not None and rank <= 3
        return f"{'✅ موفق' if ok else '❌ ناموفق'} — رتبهٔ نتیجهٔ درست: {rank} — {time.time() - t0:.1f} ثانیه"
    except Exception:  # noqa: BLE001
        return "❌ خطا:\n" + traceback.format_exc()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def log_tail(n: int = 60) -> str:
    p = os.path.join(_S["cache"], "..", "logs", "patternfinder.log")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""
