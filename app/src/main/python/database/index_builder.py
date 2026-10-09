"""مرحلهٔ اول: آماده‌سازی تصاویر کتابخانه.

1) اسکن بازگشتی پوشه (زیرپوشه‌ها هم)
2) تشخیص فایل خراب و تصویر تکراری
3) باینری‌سازی + تشخیص خودکار قطعات (وضعیت: در انتظار تأیید)
4) پس از تأیید (دستی یا «تأیید همه»): استخراج و ذخیرهٔ ویژگی‌ها

اسکن مجدد «افزایشی» است: فایل بدون تغییر دوباره پردازش نمی‌شود.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import config
from database.repository import Repository
from image_engine import pipeline
from image_engine import preprocessing as pre
from image_engine.segmentation import Region

ProgressFn = Optional[Callable[[int, int, str], None]]
CancelFn = Optional[Callable[[], bool]]


@dataclass
class ScanReport:
    total_files: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    corrupt: int = 0
    duplicates: int = 0
    cancelled: bool = False
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.total_files} فایل | جدید: {self.added} | تغییرکرده: {self.updated} | "
                f"بدون تغییر: {self.unchanged} | حذف‌شده: {self.removed} | "
                f"خراب: {self.corrupt} | تکراری: {self.duplicates}")


def iter_image_files(folder: str | Path) -> list[str]:
    exts = config.SUPPORTED_EXTENSIONS
    found: list[str] = []
    for root, _dirs, files in os.walk(str(folder)):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in exts:
                found.append(os.path.join(root, fn))
    found.sort(key=lambda p: p.lower())
    return found


def _call(progress: ProgressFn, i: int, n: int, msg: str) -> None:
    if progress:
        progress(i, n, msg)


# --------------------------------------------------------------------------- #
# اسکن
# --------------------------------------------------------------------------- #
def scan_library(
    repo: Repository,
    folder: str | Path,
    progress: ProgressFn = None,
    cancel: CancelFn = None,
    workers: int = 2,
    mode: str = "auto",
) -> ScanReport:
    rep = ScanReport()
    files = iter_image_files(folder)
    rep.total_files = len(files)
    file_set = set(files)
    prefix = os.path.normcase(os.path.abspath(str(folder)))

    # --- حذف ردیف‌هایی که فایلشان دیگر وجود ندارد (فقط داخل این پوشه) ---
    existing = repo.all_paths()
    for p, iid in existing.items():
        if os.path.normcase(os.path.abspath(p)).startswith(prefix) and p not in file_set:
            repo.delete_image(iid)
            rep.removed += 1
    # تکراری‌هایی که اصلشان حذف شد را برای پردازش مجدد علامت بزنیم
    for row in repo.list_images("duplicate"):
        if row.duplicate_of is None or repo.get_image(row.duplicate_of) is None:
            repo.update_image(row.id, size=-1)

    # --- تعیین فایل‌های جدید/تغییرکرده ---
    todo: list[tuple[str, Optional[int]]] = []
    for p in files:
        try:
            st = os.stat(p)
        except OSError as exc:
            rep.errors.append(f"{p}: {exc}")
            continue
        row = repo.get_image_by_path(p)
        if row and row.size == st.st_size and row.mtime is not None and abs(row.mtime - st.st_mtime) < 1e-3:
            rep.unchanged += 1
            continue
        todo.append((p, row.id if row else None))
    if not todo:
        return rep

    n = len(todo)
    workers = max(1, workers)

    # --- گذر ۱: SHA1 (برای تکراری‌ها) ---
    def hash_one(item):
        p, _ = item
        try:
            return pre.file_sha1(p), None
        except OSError as exc:
            return None, str(exc)

    hashes: list = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(hash_one, todo), 1):
            hashes.append(res)
            if i % 25 == 0 or i == n:
                _call(progress, i, n * 2, "بررسی تصاویر تکراری…")
            if cancel and cancel():
                rep.cancelled = True
                return rep

    to_analyze: list[tuple[str, int, str]] = []   # (path, image_id, sha1)
    for (p, known_id), (sha, err) in zip(todo, hashes):
        st = os.stat(p)
        base = dict(size=st.st_size, mtime=st.st_mtime)
        if sha is None:
            repo.upsert_image(p, status="corrupt", error=err or "خواندن فایل ممکن نیست", **base)
            rep.corrupt += 1
            continue
        original = repo.find_by_sha1(sha, exclude_id=known_id)
        if original is not None and os.path.normcase(original.path) != os.path.normcase(p):
            iid = repo.upsert_image(p, sha1=sha, status="duplicate", duplicate_of=original.id,
                                    error=f"نسخهٔ تکراری از: {original.path}", **base)
            repo.replace_entries(iid, [], None)
            rep.duplicates += 1
            continue
        iid = repo.upsert_image(p, sha1=sha, status="pending", duplicate_of=None, error=None,
                                preprocess_mode=mode, **base)
        if known_id is None:
            rep.added += 1
        else:
            rep.updated += 1
        to_analyze.append((p, iid, sha))
        # نخستین فایل با این هش، «اصل» می‌شود (برای فایل‌های بعدیِ همین دسته)

    # --- گذر ۲: باینری‌سازی و تشخیص قطعات ---
    def analyze_one(item):
        p, iid, _sha = item
        try:
            an = pipeline.analyze_image(p, mode)
            return iid, an.size, an.regions, None
        except pre.ImageLoadError as exc:
            return iid, None, None, str(exc)
        except Exception as exc:  # خطای پیش‌بینی‌نشده نباید کل اسکن را متوقف کند
            return iid, None, None, f"خطای پردازش: {exc}"

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for iid, size, regions, err in ex.map(analyze_one, to_analyze):
            done += 1
            if err or not regions:
                repo.update_image(iid, status="corrupt", error=err or "هیچ طرحی در تصویر پیدا نشد")
                repo.replace_entries(iid, [], None)
                rep.corrupt += 1
            else:
                repo.update_image(iid, width=size[0], height=size[1])
                repo.replace_entries(iid, [(r, None) for r in regions], None)
            if done % 10 == 0 or done == len(to_analyze):
                _call(progress, n + done, n * 2, "تشخیص قطعات…")
            if cancel and cancel():
                rep.cancelled = True
                break
    repo.bump_revision()
    return rep


# --------------------------------------------------------------------------- #
# اصلاح و تأیید
# --------------------------------------------------------------------------- #
def redetect(repo: Repository, image_id: int, mode: str, polarity: str = "auto") -> list[Region]:
    """تشخیص دوبارهٔ قطعات با روش پیش‌پردازش دیگر (جایگزین قطعات قبلی)."""
    row = repo.get_image(image_id)
    if row is None:
        return []
    an = pipeline.analyze_image(row.path, mode, polarity)
    repo.update_image(image_id, preprocess_mode=mode, polarity=polarity, status="pending",
                      width=an.size[0], height=an.size[1], error=None)
    repo.replace_entries(image_id, [(r, None) for r in an.regions], None)
    repo.bump_revision()
    return an.regions


def compute_entries(repo: Repository, image_id: int, regions: Optional[list[Region]] = None):
    """(parts, whole) را محاسبه می‌کند؛ نوشتن در پایگاه داده جداگانه انجام می‌شود."""
    row = repo.get_image(image_id)
    if row is None:
        raise ValueError("تصویر در پایگاه داده نیست")
    if regions is None:
        regions = repo.get_regions(image_id)
    an = pipeline.analyze_image(row.path, row.preprocess_mode or "auto", row.polarity or "auto",
                                regions=list(regions))
    parts, kept = [], []
    for r in regions:
        f = pipeline.region_features(an.binary, r)
        if f is not None:
            parts.append((r, f))
            kept.append(r)
    whole = pipeline.whole_features(an.binary, kept) if kept else None
    return parts, whole, an.size


def approve_image(repo: Repository, image_id: int, regions: Optional[list[Region]] = None) -> int:
    """ویژگی‌ها را می‌سازد و تصویر را «تأییدشده» می‌کند. خروجی: تعداد قطعات معتبر."""
    parts, whole, size = compute_entries(repo, image_id, regions)
    if not parts:
        repo.update_image(image_id, status="corrupt", error="هیچ قطعهٔ معتبری باقی نماند")
        repo.replace_entries(image_id, [], None)
        repo.bump_revision()
        return 0
    repo.replace_entries(image_id, parts, whole)
    repo.update_image(image_id, status="approved", width=size[0], height=size[1], error=None)
    repo.bump_revision()
    return len(parts)


def approve_all(
    repo: Repository,
    image_ids: Optional[Iterable[int]] = None,
    progress: ProgressFn = None,
    cancel: CancelFn = None,
    workers: int = 2,
) -> int:
    """تأیید دسته‌ای (قطعات تشخیص‌داده‌شده همان‌طور که هستند). پیش‌فرض: همهٔ «در انتظار»."""
    if image_ids is None:
        ids = [r.id for r in repo.list_images("pending")]
    else:
        ids = list(image_ids)
    n = len(ids)
    ok = 0

    def work(iid):
        try:
            return iid, compute_entries(repo, iid), None
        except Exception as exc:
            return iid, None, str(exc)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for i, (iid, res, err) in enumerate(ex.map(work, ids), 1):
            if res is None or not res[0]:
                repo.update_image(iid, status="corrupt", error=err or "هیچ قطعهٔ معتبری یافت نشد")
                repo.replace_entries(iid, [], None)
            else:
                parts, whole, size = res
                repo.replace_entries(iid, parts, whole)
                repo.update_image(iid, status="approved", width=size[0], height=size[1], error=None)
                ok += 1
            if i % 5 == 0 or i == n:
                _call(progress, i, n, "استخراج ویژگی‌ها…")
            if cancel and cancel():
                break
    repo.bump_revision()
    return ok
