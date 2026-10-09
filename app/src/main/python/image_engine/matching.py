"""موتور جستجو: مقایسهٔ ویژگی‌های پرسش با شاخص کتابخانه.

مراحل جستجوی قطعه
-----------------
1. شباهت برداری سریع (شکل/هندسه/چیدمان/خطوط) با همهٔ قطعات کتابخانه (NumPy).
2. بازرتبه‌بندی دقیق‌ترِ بهترین‌ها با تطبیق محلی ORB + RANSAC (مقاوم به چرخش و اندازه).
3. «جستجوی عمیق»: تطبیق ORB قطعه با کل هر تصویر؛ برای وقتی که قطعه در تشخیص
   خودکار جدا نشده یا داخل یک طرح بزرگ‌تر قرار دارد. محل دقیق قطعه هم از همین‌جا می‌آید.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

import config
from database.repository import Repository
from image_engine import ranking
from image_engine.geometry_features import Features, unpack_orb
from image_engine.ranking import SearchResult

ProgressFn = Optional[Callable[[int, int, str], None]]
CancelFn = Optional[Callable[[], bool]]

_RANSAC_THR = 3.0          # پیکسل در فضای نرمال‌شدهٔ هدف
_MAX_HAMMING = 80          # از ۲۵۶ بیت
_MIN_INLIERS = 8


# --------------------------------------------------------------------------- #
# شباهت برداری
# --------------------------------------------------------------------------- #
def gaussian_sim(q: np.ndarray, M: np.ndarray, scale: float) -> np.ndarray:
    """شباهت ∈ (0,1] بر اساس فاصلهٔ RMS."""
    if M.shape[0] == 0:
        return np.zeros(0, np.float32)
    d = np.sqrt(np.mean((M - q[None, :]) ** 2, axis=1))
    return np.exp(-((d / scale) ** 2)).astype(np.float32)


# --------------------------------------------------------------------------- #
# تطبیق ORB
# --------------------------------------------------------------------------- #
@dataclass
class OrbMatch:
    score: float = 0.0
    inliers: int = 0
    M: Optional[np.ndarray] = None


_bf_local = None


def _matcher():
    # BFMatcher بین threadها به‌اشتراک گذاشته نمی‌شود؛ هر بار می‌سازیم (ارزان است)
    return cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)


def orb_match(q_des, q_pts, t_des, t_pts, matcher=None) -> OrbMatch:
    nq, nt = len(q_des), len(t_des)
    if nq < _MIN_INLIERS or nt < _MIN_INLIERS:
        return OrbMatch()
    bf = matcher or _matcher()
    try:
        matches = bf.match(q_des, t_des)
    except cv2.error:
        return OrbMatch()
    good = [m for m in matches if m.distance <= _MAX_HAMMING]
    if len(good) < _MIN_INLIERS:
        return OrbMatch()
    src = np.float32([q_pts[m.queryIdx] for m in good]).reshape(-1, 1, 2)
    dst = np.float32([t_pts[m.trainIdx] for m in good]).reshape(-1, 1, 2)
    M, inl = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=_RANSAC_THR,
        maxIters=800, confidence=0.99)
    if M is None or inl is None:
        return OrbMatch()
    n_in = int(inl.sum())
    if n_in < _MIN_INLIERS:
        return OrbMatch()
    s = math.sqrt(abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]))
    if not (0.08 < s < 12.0):
        return OrbMatch()
    # امتیاز مطلق: ۸ inlier یا کمتر ≈ شانسی؛ از ۲۶ inlier به بالا ≈ تطبیق کامل
    score = min(1.0, max(0.0, (n_in - 8.0) / 18.0))
    return OrbMatch(score=float(score), inliers=n_in, M=M)


def _project_polygon(q: Features, M: np.ndarray, t_scale: float, t_origin: tuple) -> list:
    """گوشه‌های کادر قطعهٔ پرسش را به فضای تصویر کتابخانه می‌برد."""
    w, h = q.bbox[2] * q.orb_scale, q.bbox[3] * q.orb_scale
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    t = cv2.transform(corners, M).reshape(-1, 2)
    t = t / max(t_scale, 1e-9) + np.float32(t_origin)
    return [(float(x), float(y)) for x, y in t]


def _bbox_polygon(x, y, w, h) -> list:
    return [(float(x), float(y)), (float(x + w), float(y)),
            (float(x + w), float(y + h)), (float(x), float(y + h))]


# --------------------------------------------------------------------------- #
# شاخص کتابخانه
# --------------------------------------------------------------------------- #
class LibraryIndex:
    """نمایش حافظه‌ای ویژگی‌های کتابخانه برای جستجوی سریع."""

    def __init__(self, repo: Repository, deep_scan: bool = True, workers: int = 0):
        self.repo = repo
        import os
        self.workers = workers or max(1, min(8, (os.cpu_count() or 2) - 1))
        self.deep_scan = deep_scan
        self.revision = -1
        self.n = 0
        self._orb_cache: dict[int, tuple] = {}

    # ------------------------------------------------------------------ #
    def is_stale(self) -> bool:
        return self.revision != self.repo.revision()

    def load(self, progress: ProgressFn = None) -> int:
        rev = self.repo.revision()
        rows = self.repo.fetch_index_rows()
        n = len(rows)
        self.n = n
        self.ids = np.zeros(n, np.int64)
        self.image_ids = np.zeros(n, np.int64)
        self.is_part = np.zeros(n, bool)
        self.bbox = np.zeros((n, 4), np.float32)
        self.orb_scale = np.ones(n, np.float32)
        self.shape = np.zeros((n, 0), np.float32)
        from image_engine import geometry_features as gf
        self.shape = np.zeros((n, gf.SHAPE_DIM), np.float32)
        self.geom = np.zeros((n, gf.GEOM_DIM), np.float32)
        self.layout = np.zeros((n, gf.LAYOUT_DIM), np.float32)
        self.lines = np.zeros((n, gf.LINES_DIM), np.float32)
        for i, (cid, iid, kind, x, y, w, h, sh, ge, la, li, _on, osc) in enumerate(rows):
            self.ids[i], self.image_ids[i] = cid, iid
            self.is_part[i] = (kind == "part")
            self.bbox[i] = (x, y, w, h)
            self.orb_scale[i] = osc or 1.0
            self.shape[i] = np.frombuffer(sh, np.float32)
            self.geom[i] = np.frombuffer(ge, np.float32)
            self.layout[i] = np.frombuffer(la, np.float32)
            self.lines[i] = np.frombuffer(li, np.float32)
            if progress and i % 2000 == 0:
                progress(i, n, "بارگذاری شاخص…")
        self.row_of = {int(c): i for i, c in enumerate(self.ids)}

        self.whole_orb: dict[int, tuple] = {}
        if self.deep_scan:
            for cid, on, des, pts in self.repo.fetch_whole_orb():
                d, p = unpack_orb(des, pts, on)
                if len(d) >= _MIN_INLIERS:
                    self.whole_orb[int(cid)] = (d, p)
        self._orb_cache.clear()
        self.revision = rev
        return n

    # ------------------------------------------------------------------ #
    def _orbs_for(self, entry_ids: list[int]) -> dict[int, tuple]:
        need = [e for e in entry_ids if e not in self._orb_cache]
        if need:
            for cid, (n, des, pts) in self.repo.fetch_orb(need).items():
                self._orb_cache[cid] = unpack_orb(des, pts, n)
        if len(self._orb_cache) > 8000:
            self._orb_cache.clear()
            for cid, (n, des, pts) in self.repo.fetch_orb(entry_ids).items():
                self._orb_cache[cid] = unpack_orb(des, pts, n)
        return {e: self._orb_cache.get(e, (np.zeros((0, 32), np.uint8), np.zeros((0, 2), np.float32)))
                for e in entry_ids}

    def _vector_sims(self, q: Features, rows: np.ndarray) -> dict[str, np.ndarray]:
        sc = config.SIM_SCALES
        return {
            "shape": gaussian_sim(q.shape, self.shape[rows], sc["shape"]),
            "geom": gaussian_sim(q.geom, self.geom[rows], sc["geom"]),
            "layout": gaussian_sim(q.layout, self.layout[rows], sc["layout"]),
            "lines": gaussian_sim(q.lines, self.lines[rows], sc["lines"]),
        }

    # ------------------------------------------------------------------ #
    # جستجوی قطعه
    # ------------------------------------------------------------------ #
    def component_candidates(
        self, q: Features, weights: Optional[dict] = None, rerank: int = 150,
        progress: ProgressFn = None, cancel: CancelFn = None,
    ) -> dict[int, SearchResult]:
        """بهترین نتیجهٔ هر تصویر (کلید: image_id)."""
        w = ranking.normalize_weights(weights)
        best: dict[int, tuple[float, dict, int, str, str, list]] = {}

        def offer(image_id, score, parts, entry_id, kind, mtype, poly):
            cur = best.get(image_id)
            if cur is None or score > cur[0]:
                best[image_id] = (score, parts, entry_id, kind, mtype, poly)

        # --- گام ۱ و ۲: قطعات ---
        part_rows = np.nonzero(self.is_part)[0]
        if len(part_rows):
            sims = self._vector_sims(q, part_rows)
            coarse = (w["shape"] * sims["shape"] + w["geom"] * sims["geom"]
                      + w["layout"] * sims["layout"] + w["local"] * sims["lines"])
            order = np.argsort(-coarse)[:rerank]
            sel_rows = part_rows[order]
            sel_ids = [int(self.ids[r]) for r in sel_rows]
            orbs = self._orbs_for(sel_ids)
            bf = _matcher()
            has_q_orb = len(q.orb_des) >= _MIN_INLIERS
            for j, r in enumerate(sel_rows):
                eid = sel_ids[j]
                k = order[j]
                lines_s = float(sims["lines"][k])
                om = OrbMatch()
                t_des, t_pts = orbs[eid]
                if has_q_orb and len(t_des) >= _MIN_INLIERS:
                    om = orb_match(q.orb_des, q.orb_pts, t_des, t_pts, bf)
                    local = 0.5 * lines_s + 0.5 * om.score if om.M is not None else 0.75 * lines_s
                else:
                    local = lines_s
                parts = {"shape": float(sims["shape"][k]), "local": local,
                         "geom": float(sims["geom"][k]), "layout": float(sims["layout"][k])}
                total = ranking.combine(parts, w)
                mtype = "component"
                contained = config.CONTAINED_MATCH_TRUST * om.score
                if om.M is not None and contained > total:
                    total, mtype = contained, "contained"
                    parts = dict(parts, local=om.score)
                x, y, bw, bh = self.bbox[r]
                poly = _bbox_polygon(x, y, bw, bh)
                if om.M is not None:
                    poly = _project_polygon(q, om.M, float(self.orb_scale[r]), (float(x), float(y)))
                offer(int(self.image_ids[r]), total, parts, eid, "part", mtype, poly)
                if cancel and j % 50 == 0 and cancel():
                    break

        # --- گام ۳: جستجوی عمیق در کل تصویرها (چندنخی) ---
        if self.deep_scan and self.whole_orb and len(q.orb_des) >= _MIN_INLIERS:
            step = max(1, int(math.ceil(len(q.orb_des) / 250.0)))   # زیرنمونه برای سرعت
            qd, qp = q.orb_des[::step], q.orb_pts[::step]
            items = list(self.whole_orb.items())
            total_n = len(items)
            chunk = 200
            stop = {"v": False}

            def work(lo):
                bf = _matcher()
                found = []
                for eid, (t_des, t_pts) in items[lo:lo + chunk]:
                    if stop["v"]:
                        break
                    om = orb_match(qd, qp, t_des, t_pts, bf)
                    if om.M is not None and om.score >= 0.25:
                        found.append((eid, om))
                return found

            from concurrent.futures import ThreadPoolExecutor
            done = 0
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                for found in ex.map(work, range(0, total_n, chunk)):
                    done += chunk
                    for eid, om in found:
                        r = self.row_of[eid]
                        x, y, _bw, _bh = self.bbox[r]
                        poly = _project_polygon(q, om.M, float(self.orb_scale[r]), (float(x), float(y)))
                        parts = {"shape": 0.0, "local": om.score, "geom": 0.0, "layout": 0.0}
                        offer(int(self.image_ids[r]), config.CONTAINED_MATCH_TRUST * om.score,
                              parts, eid, "whole", "contained", poly)
                    if progress:
                        progress(min(done, total_n), total_n, "جستجوی عمیق در تصاویر…")
                    if cancel and cancel():
                        stop["v"] = True

        out: dict[int, SearchResult] = {}
        for iid, (score, parts, eid, kind, mtype, poly) in best.items():
            out[iid] = SearchResult(image_id=iid, path="", score=float(score), parts=parts,
                                    polygon=poly, entry_id=eid, entry_kind=kind,
                                    match_type=mtype, component_score=float(score))
        return out

    # ------------------------------------------------------------------ #
    def whole_scores(self, q_whole: Features, weights: Optional[dict] = None) -> dict[int, tuple[float, dict]]:
        """شباهت کل طرح پرسش با کل طرح هر تصویر (فقط شباهت برداری)."""
        w = ranking.normalize_weights(weights)
        rows = np.nonzero(~self.is_part)[0]
        if not len(rows):
            return {}
        sims = self._vector_sims(q_whole, rows)
        parts_arr = {"shape": sims["shape"], "local": sims["lines"],
                     "geom": sims["geom"], "layout": sims["layout"]}
        total = sum(w[k] * parts_arr[k] for k in ranking.PART_KEYS)
        return {int(self.image_ids[r]): (float(total[i]),
                                          {k: float(parts_arr[k][i]) for k in ranking.PART_KEYS})
                for i, r in enumerate(rows)}

    # ------------------------------------------------------------------ #
    # نقطهٔ ورود جستجو
    # ------------------------------------------------------------------ #
    def search(
        self,
        q_component: Features,
        q_whole: Optional[Features] = None,
        mode: str = "component",
        weights: Optional[dict] = None,
        top_k: int = 30,
        rerank: int = 150,
        progress: ProgressFn = None,
        cancel: CancelFn = None,
    ) -> list[SearchResult]:
        if self.n == 0:
            return []
        comp = self.component_candidates(q_component, weights, rerank, progress, cancel)
        results: dict[int, SearchResult] = {}

        if mode == "combined" and q_whole is not None:
            whole = self.whole_scores(q_whole, weights)
            share = config.COMBINED_COMPONENT_SHARE
            for iid in set(comp) | set(whole):
                c = comp.get(iid)
                ws, wparts = whole.get(iid, (0.0, {}))
                cs = c.score if c else 0.0
                total = share * cs + (1 - share) * ws
                r = c or SearchResult(image_id=iid, path="", score=0.0, parts=dict(wparts),
                                      match_type="image")
                r.component_score, r.image_score, r.score = cs, ws, total
                if c is None and iid in whole:
                    rows = np.nonzero((self.image_ids == iid) & ~self.is_part)[0]
                    if len(rows):
                        x, y, bw, bh = self.bbox[rows[0]]
                        r.polygon = _bbox_polygon(x, y, bw, bh)
                results[iid] = r
        else:
            results = comp

        top = ranking.rank_results(list(results.values()), top_k)
        info = self.repo.image_paths([r.image_id for r in top])
        for r in top:
            r.path, r.width, r.height = info.get(r.image_id, ("", 0, 0))
        return top
