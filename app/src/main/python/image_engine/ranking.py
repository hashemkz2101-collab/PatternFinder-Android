"""امتیاز ترکیبی و رتبه‌بندی نتایج."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import config

PART_KEYS = ("shape", "local", "geom", "layout")


def normalize_weights(weights: Optional[dict]) -> dict:
    w = {k: max(0.0, float((weights or {}).get(k, config.DEFAULT_WEIGHTS[k]))) for k in PART_KEYS}
    s = sum(w.values())
    if s <= 0:
        return dict(config.DEFAULT_WEIGHTS)
    return {k: v / s for k, v in w.items()}


def combine(parts: dict, weights: Optional[dict] = None) -> float:
    w = normalize_weights(weights)
    return float(sum(w[k] * float(parts.get(k, 0.0)) for k in PART_KEYS))


@dataclass
class SearchResult:
    image_id: int
    path: str
    score: float
    parts: dict = field(default_factory=dict)        # shape/local/geom/layout
    polygon: list = field(default_factory=list)      # محل قطعه در تصویر کاری
    entry_id: int = 0
    entry_kind: str = "part"                          # part | whole
    match_type: str = "component"                     # component | contained | image
    component_score: float = 0.0
    image_score: float = 0.0
    width: int = 0
    height: int = 0
    preview: object = None                            # آرایهٔ RGB پیش‌نمایش (اختیاری)

    def label(self) -> str:
        return {"component": "قطعهٔ مشابه", "contained": "قطعه داخل طرح بزرگ‌تر",
                "image": "طرح مشابه"}.get(self.match_type, "")


def rank_results(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]


def rank_of(results: list[SearchResult], expected_image_id: int) -> Optional[int]:
    """رتبهٔ (۱-مبنا) تصویر مورد انتظار در نتایج، یا None."""
    for i, r in enumerate(results, 1):
        if r.image_id == expected_image_id:
            return i
    return None
