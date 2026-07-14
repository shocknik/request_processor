"""
Fuzzy-сопоставление OCR-марки с эталонами из cable_marks.

Детерминированный слой: SequenceMatcher + нормализация пробелов/регистра.
Не пишет в БД — только кандидаты для MarkCorrector / оператора.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable


def _compact(mark: str) -> str:
    """Сжимает марку для сравнения: нижний регистр, без лишних пробелов."""
    s = (mark or "").strip().lower()
    s = s.replace("×", "х").replace("x", "х")
    s = re.sub(r"\s+", "", s)
    s = s.replace("ё", "е")
    return s


def similarity(a: str, b: str) -> float:
    """0..1 — похожесть двух обозначений."""
    ca, cb = _compact(a), _compact(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    return SequenceMatcher(None, ca, cb).ratio()


def _brand_token(mark: str) -> str:
    """Первые буквы бренда (до нг/размера) для защиты от ложного fuzzy."""
    s = re.sub(r"\s+", "", (mark or "").upper())
    s = s.replace("×", "Х").replace("X", "Х")
    m = re.match(r"^([А-ЯЁA-Z]{2,10})", s)
    if not m:
        return ""
    tok = m.group(1)
    # отрезать пожарный класс
    tok = re.split(r"НГ|NG|LS|HF|FR", tok, maxsplit=1)[0]
    return tok[:6]


def _brand_compatible(a: str, b: str) -> bool:
    ta, tb = _brand_token(a), _brand_token(b)
    if not ta or not tb:
        return True  # нечего сравнить — не режем
    if ta == tb:
        return True
    # общий префикс ≥ 3 (КСБ / КСБГ)
    n = min(len(ta), len(tb), 4)
    return n >= 3 and ta[:n] == tb[:n]


def best_mark_matches(
    raw: str,
    candidates: Iterable[str],
    *,
    limit: int = 5,
    min_score: float = 0.72,
    require_brand: bool = True,
) -> list[tuple[str, float]]:
    """
    Топ кандидатов по похожести.

    Returns:
        list of (candidate_mark, score) sorted desc.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    scored: list[tuple[str, float]] = []
    seen: set[str] = set()
    for cand in candidates:
        c = (cand or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        if require_brand and not _brand_compatible(raw, c):
            continue
        score = similarity(raw, c)
        if score >= min_score:
            scored.append((c, score))
    scored.sort(key=lambda x: (-x[1], len(x[0])))
    return scored[:limit]


def fuzzy_snap_mark(
    raw: str,
    candidates: Iterable[str],
    *,
    min_score: float = 0.86,
) -> tuple[str | None, float]:
    """
    Возвращает лучший эталон, если score ≥ min_score.

    Порог 0.86 — осторожный snap; бренд-префикс должен совпадать
    (КСБ ≠ ПВС даже при похожем «нг-LS 3х2,5»).
    """
    matches = best_mark_matches(raw, candidates, limit=1, min_score=min_score)
    if not matches:
        return None, 0.0
    return matches[0][0], matches[0][1]
