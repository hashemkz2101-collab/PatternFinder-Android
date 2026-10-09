"""دسترسی به SQLite (امن برای چند Thread: هر Thread اتصال خودش را دارد)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

import config
from database.models import SCHEMA, ImageRow
from image_engine.geometry_features import Features
from image_engine.segmentation import Region

_IMG_COLS = ("id, path, sha1, size, mtime, width, height, status, duplicate_of, "
             "preprocess_mode, polarity, error")


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._local = threading.local()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    # ------------------------------------------------------------------ #
    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, timeout=60)
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA journal_mode = WAL")
            c.execute("PRAGMA synchronous = NORMAL")
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    # ------------------------------------------------------------------ #
    # meta / نسخهٔ داده
    # ------------------------------------------------------------------ #
    def get_meta(self, key: str, default: str = "") -> str:
        r = self._conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def revision(self) -> int:
        return int(self.get_meta("revision", "0") or 0)

    def bump_revision(self) -> None:
        self.set_meta("revision", str(self.revision() + 1))

    # ------------------------------------------------------------------ #
    # تصاویر
    # ------------------------------------------------------------------ #
    @staticmethod
    def _row(r) -> ImageRow:
        return ImageRow(*r)

    def get_image(self, image_id: int) -> Optional[ImageRow]:
        r = self._conn().execute(f"SELECT {_IMG_COLS} FROM images WHERE id=?", (image_id,)).fetchone()
        return self._row(r) if r else None

    def get_image_by_path(self, path: str) -> Optional[ImageRow]:
        r = self._conn().execute(f"SELECT {_IMG_COLS} FROM images WHERE path=?", (path,)).fetchone()
        return self._row(r) if r else None

    def list_images(self, status: Optional[str] = None) -> list[ImageRow]:
        q = f"SELECT {_IMG_COLS} FROM images"
        args: tuple = ()
        if status:
            q += " WHERE status=?"
            args = (status,)
        q += " ORDER BY path COLLATE NOCASE"
        return [self._row(r) for r in self._conn().execute(q, args)]

    def all_paths(self) -> dict[str, int]:
        return {r[1]: r[0] for r in self._conn().execute("SELECT id, path FROM images")}

    def find_by_sha1(self, sha1: str, exclude_id: Optional[int] = None) -> Optional[ImageRow]:
        q = f"SELECT {_IMG_COLS} FROM images WHERE sha1=? AND status != 'duplicate'"
        args: list = [sha1]
        if exclude_id is not None:
            q += " AND id != ?"
            args.append(exclude_id)
        q += " ORDER BY id LIMIT 1"
        r = self._conn().execute(q, args).fetchone()
        return self._row(r) if r else None

    def upsert_image(self, path: str, **fields) -> int:
        fields["updated"] = time.time()
        with self._conn() as c:
            row = c.execute("SELECT id FROM images WHERE path=?", (path,)).fetchone()
            if row:
                sets = ", ".join(f"{k}=?" for k in fields)
                c.execute(f"UPDATE images SET {sets} WHERE id=?", (*fields.values(), row[0]))
                return row[0]
            cols = ", ".join(["path", *fields])
            qs = ", ".join("?" * (1 + len(fields)))
            cur = c.execute(f"INSERT INTO images({cols}) VALUES({qs})", (path, *fields.values()))
            return int(cur.lastrowid)

    def update_image(self, image_id: int, **fields) -> None:
        fields["updated"] = time.time()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE images SET {sets} WHERE id=?", (*fields.values(), image_id))

    def delete_image(self, image_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM images WHERE id=?", (image_id,))

    def count_by_status(self) -> dict[str, int]:
        out = {"pending": 0, "approved": 0, "corrupt": 0, "duplicate": 0}
        for st, n in self._conn().execute("SELECT status, COUNT(*) FROM images GROUP BY status"):
            out[st] = n
        return out

    # ------------------------------------------------------------------ #
    # قطعات
    # ------------------------------------------------------------------ #
    def get_regions(self, image_id: int) -> list[Region]:
        rows = self._conn().execute(
            "SELECT x,y,w,h,polygon,source FROM components "
            "WHERE image_id=? AND kind='part' ORDER BY idx", (image_id,)).fetchall()
        out = []
        for x, y, w, h, poly, src in rows:
            p = [tuple(pt) for pt in json.loads(poly)] if poly else None
            out.append(Region(x, y, w, h, p, src or "auto"))
        return out

    def replace_entries(
        self,
        image_id: int,
        parts: list[tuple[Region, Optional[Features]]],
        whole: Optional[Features] = None,
    ) -> None:
        """همهٔ قطعات + ورودی «کل طرح» این تصویر را یکجا جایگزین می‌کند."""
        with self._conn() as c:
            c.execute("DELETE FROM components WHERE image_id=?", (image_id,))
            for i, (reg, feat) in enumerate(parts):
                self._insert(c, image_id, "part", i, reg.bbox if feat is None else feat.bbox,
                             reg.polygon, reg.source, feat)
            if whole is not None:
                self._insert(c, image_id, "whole", 0, whole.bbox, None, "auto", whole)

    @staticmethod
    def _insert(c, image_id, kind, idx, bbox, polygon, source, feat: Optional[Features]):
        poly = json.dumps(polygon) if polygon else None
        base = (image_id, kind, idx, *bbox, poly, source)
        if feat is None:
            c.execute("INSERT INTO components(image_id,kind,idx,x,y,w,h,polygon,source) "
                      "VALUES(?,?,?,?,?,?,?,?,?)", base)
        else:
            c.execute(
                "INSERT INTO components(image_id,kind,idx,x,y,w,h,polygon,source,"
                "shape,geom,layout,lines,orb_n,orb_scale,orb_des,orb_pts,feat_version) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (*base, *feat.to_row(), config.FEATURE_VERSION))

    # ------------------------------------------------------------------ #
    # دادهٔ شاخص جستجو
    # ------------------------------------------------------------------ #
    def fetch_index_rows(self) -> list[tuple]:
        """ردیف‌های دارای ویژگی، فقط برای تصاویر تأییدشده."""
        return self._conn().execute(
            "SELECT c.id, c.image_id, c.kind, c.x, c.y, c.w, c.h, c.shape, c.geom, c.layout, "
            "c.lines, c.orb_n, c.orb_scale FROM components c JOIN images i ON i.id=c.image_id "
            "WHERE i.status='approved' AND c.shape IS NOT NULL AND c.feat_version=?",
            (config.FEATURE_VERSION,)).fetchall()

    def fetch_orb(self, entry_ids: Iterable[int]) -> dict[int, tuple]:
        ids = list(entry_ids)
        out: dict[int, tuple] = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            qs = ",".join("?" * len(chunk))
            for cid, n, des, pts in self._conn().execute(
                    f"SELECT id, orb_n, orb_des, orb_pts FROM components WHERE id IN ({qs})", chunk):
                out[cid] = (n, des, pts)
        return out

    def fetch_whole_orb(self) -> list[tuple]:
        return self._conn().execute(
            "SELECT c.id, c.orb_n, c.orb_des, c.orb_pts FROM components c "
            "JOIN images i ON i.id=c.image_id WHERE c.kind='whole' AND i.status='approved' "
            "AND c.orb_n>0 AND c.feat_version=?", (config.FEATURE_VERSION,)).fetchall()

    def image_paths(self, ids: Iterable[int]) -> dict[int, tuple[str, int, int]]:
        ids = list(ids)
        out = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            qs = ",".join("?" * len(chunk))
            for r in self._conn().execute(
                    f"SELECT id, path, COALESCE(width,0), COALESCE(height,0) FROM images WHERE id IN ({qs})",
                    chunk):
                out[r[0]] = (r[1], r[2], r[3])
        return out
