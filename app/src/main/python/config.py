"""تنظیمات مرکزی PatternFinder (مسیرها، ثابت‌ها، تنظیمات کاربر)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "PatternFinder"
APP_TITLE = "جستجوگر طرح (PatternFinder)"
APP_VERSION = "1.0.0"
IS_FROZEN = bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------- #
# مسیرها
# --------------------------------------------------------------------------- #
def _base_dir() -> Path:
    if IS_FROZEN:  # نسخه PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _resolve_data_dir() -> Path:
    env = os.environ.get("PATTERNFINDER_DATA")
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return p
    preferred = _base_dir() / "data"
    if _writable(preferred):
        return preferred
    # مثلاً وقتی برنامه در Program Files نصب شده و اجازه نوشتن نیست
    local = os.environ.get("LOCALAPPDATA") or str(Path.home())
    fallback = Path(local) / APP_NAME / "data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


ROOT = _base_dir()
DATA_DIR = _resolve_data_dir()
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "patternfinder.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
for _d in (CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
# ثابت‌های پردازش تصویر
# --------------------------------------------------------------------------- #
SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".tif", ".tiff", ".webp", ".gif",
}

# همهٔ مختصات (کادر قطعات، چندضلعی‌ها، محل نتیجه) در «تصویر کاری» ذخیره می‌شوند؛
# یعنی تصویر اصلی با حداکثر ضلع این مقدار (اگر بزرگ‌تر باشد کوچک می‌شود).
PROCESS_MAX_SIDE = 1200

FEATURE_VERSION = 1  # با تغییر الگوریتم ویژگی‌ها، افزایش دهید تا بازسازی شود

PREPROCESS_MODES = {
    "auto": "خودکار (پیشنهادی)",
    "otsu": "تصویر تمیز سیاه‌وسفید",
    "scan": "اسکن / نور ناهمگن",
    "faint": "طرح کم‌رنگ",
    "adaptive": "خطوط ظریف (آستانهٔ محلی)",
    "texture": "بافت‌دار / پس‌زمینه شلوغ",
}
POLARITY_MODES = {
    "auto": "تشخیص خودکار",
    "dark_on_light": "طرح تیره روی زمینهٔ روشن",
    "light_on_dark": "طرح روشن روی زمینهٔ تیره",
}

# اندازه‌های نرمال‌سازی برای استخراج ویژگی
NORM_SIZE = 192          # ویژگی‌های هندسی
ORB_SIZE_PART = 256      # ORB برای قطعه
ORB_SIZE_WHOLE = 512     # ORB برای کل طرح تصویر
ORB_FEATURES_PART = 400
ORB_FEATURES_WHOLE = 400

# وزن‌های اولیهٔ امتیاز (طبق سند: ۴۰ / ۳۰ / ۲۰ / ۱۰) - باید با نمونهٔ واقعی تنظیم شوند
DEFAULT_WEIGHTS = {"shape": 0.40, "local": 0.30, "geom": 0.20, "layout": 0.10}
WEIGHT_LABELS = {
    "shape": "شباهت شکل و کانتور",
    "local": "شباهت خطوط و ویژگی‌های محلی",
    "geom": "تناسبات و ساختار هندسی",
    "layout": "شباهت چیدمان",
}

# مقیاس تبدیل فاصله به شباهت: sim = exp(-(rms_distance / scale)^2)
SIM_SCALES = {"shape": 0.10, "geom": 0.16, "layout": 0.10, "lines": 0.07}

# ترکیب «جستجوی ترکیبی»: سهم قطعه و تصویر مادر
COMBINED_COMPONENT_SHARE = 0.65
# ضریب اعتماد به تطبیق ORB وقتی قطعه «داخل» یک طرح بزرگ‌تر پیدا شده است
CONTAINED_MATCH_TRUST = 0.85


@dataclass
class Settings:
    last_library: str = ""
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    top_k: int = 30
    rerank: int = 150
    deep_scan: bool = True          # جستجوی قطعه داخل کل تصویرها (کندتر ولی کامل‌تر)
    default_mode: str = "auto"
    workers: int = 0                # 0 = خودکار

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or SETTINGS_PATH
        s = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        for k, v in DEFAULT_WEIGHTS.items():
            s.weights.setdefault(k, v)
        return s

    def save(self, path: Path | None = None) -> None:
        path = path or SETTINGS_PATH
        try:
            Path(path).write_text(
                json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def worker_count(self) -> int:
        if self.workers and self.workers > 0:
            return self.workers
        return max(1, min(8, (os.cpu_count() or 2) - 1))
