"""ساختار جدول‌ها و مدل‌های دادهٔ پایگاه SQLite."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    sha1 TEXT,
    size INTEGER,
    mtime REAL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | corrupt | duplicate
    duplicate_of INTEGER,
    preprocess_mode TEXT DEFAULT 'auto',
    polarity TEXT DEFAULT 'auto',
    error TEXT,
    updated REAL
);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
CREATE INDEX IF NOT EXISTS idx_images_sha1 ON images(sha1);
CREATE TABLE IF NOT EXISTS components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                        -- part | whole
    idx INTEGER NOT NULL DEFAULT 0,
    x INTEGER, y INTEGER, w INTEGER, h INTEGER,
    polygon TEXT,
    source TEXT DEFAULT 'auto',
    shape BLOB, geom BLOB, layout BLOB, lines BLOB,
    orb_n INTEGER DEFAULT 0,
    orb_scale REAL DEFAULT 1.0,
    orb_des BLOB, orb_pts BLOB,
    feat_version INTEGER
);
CREATE INDEX IF NOT EXISTS idx_comp_image ON components(image_id);
"""


@dataclass
class ImageRow:
    id: int
    path: str
    sha1: Optional[str]
    size: Optional[int]
    mtime: Optional[float]
    width: Optional[int]
    height: Optional[int]
    status: str
    duplicate_of: Optional[int]
    preprocess_mode: str
    polarity: str
    error: Optional[str]

    STATUS_LABELS = {
        "pending": "در انتظار تأیید",
        "approved": "تأییدشده",
        "corrupt": "خراب / بدون طرح",
        "duplicate": "تکراری",
    }

    @property
    def status_label(self) -> str:
        return self.STATUS_LABELS.get(self.status, self.status)
