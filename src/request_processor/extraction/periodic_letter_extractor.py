"""
Извлечение марок из письма на периодические испытания (таблица Калужа и аналоги).

OCR часто склеивает номер строки «1» с «3х4ок» → «13х4ок» и цены из соседних колонок.
"""

from __future__ import annotations

import re

from ..models import CableMarkMatch
from ..parsing.cable_mark_parser import extract_document_from_text
from .ocr_mark_normalizer import normalize_mark_after_ocr

_PERIODIC_MARKER = re.compile(
    r"периодическ|Nnepuoauyeckie|NMpocum\s+Bac\s+nprovectm",
    re.IGNORECASE,
)

_SIZE_X = r"[xх×]"

# Таблица Калужа без слова «периодические» (скопирована из PDF / OCR таблицы)
_KALUGA_TABLE_HINT = re.compile(
    rf"(?:^|\s)(?:13{_SIZE_X}4ок\s*\(N|"
    rf"[1-4]\s+(?:ПВСнг|NBCur|АПуВ|AllyB|ПБГВВ|NBIBB))",
    re.IGNORECASE,
)

# «13x4ок» = номер строки 1 + «3x4ок» (после normalize_text_for_marks «х» → «x»)
_ROW1_GLUE = re.compile(rf"^13({_SIZE_X}4ок)", re.IGNORECASE)
_ROW_PREFIX = re.compile(r"^[1-4]\s+")


def is_periodic_letter(text: str) -> bool:
    if not text:
        return False
    head = text[:4000]
    if _PERIODIC_MARKER.search(head) or _KALUGA_TABLE_HINT.search(head):
        return True
    try:
        from .families.registry import get_family_registry

        family = get_family_registry().get("kaluga_periodic_v1")
        if family and family.is_confident_match(text):
            return True
    except Exception:
        pass
    return False


def _clean_periodic_mark(raw: str) -> str:
    mark = raw.strip(" .,;:\t")
    mark = _ROW_PREFIX.sub("", mark)
    mark = _ROW1_GLUE.sub(r"3\1", mark)
    return normalize_mark_after_ocr(mark)


def _canonical_periodic_mark(mark: str) -> str:
    """Единый вид для дедупликации и сортировки."""
    compact = re.sub(r"\s+", "", mark.lower())
    compact = compact.replace("x", "х")
    return compact


def _row_sort_key(mark: str) -> int:
    low = mark.lower()
    if "4ок" in low and "(n" in low.replace(" ", ""):
        return 1
    if "пвс" in low:
        return 2
    if "апув" in low:
        return 3
    if "пбгвв" in low:
        return 4
    return 99


def extract_marks_from_periodic_letter(text: str) -> list[CableMarkMatch]:
    """
    Структурное извлечение 4 марок из письма на периодические испытания.
    """
    if not is_periodic_letter(text):
        return []

    found: list[tuple[str, int, int, str | None]] = []

    patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "cable",
            re.compile(
                rf"(?:Кабель\s+силовой\s+марк[аи]:|BBI-MHr\(A\)|ВВГнг\(А\))\s*"
                rf"((?:ВВГнг\(А\)\s*)?3{_SIZE_X}?4ок\s*\(N,?\s*PE\)-0,66)",
                re.IGNORECASE,
            ),
        ),
        (
            "wire",
            re.compile(
                rf"(ПВСнг\(А\)-LS\s*3{_SIZE_X}?2,50|NBCur\(A\)-LS\s*3x2,50)",
                re.IGNORECASE,
            ),
        ),
        (
            "product",
            re.compile(
                rf"Провод\s+марк[аи]\s+"
                rf"(АПуВ\s*1{_SIZE_X}?6|AllyB\s*1x6|ПБГВВ\s*2{_SIZE_X}?1,5|NBIBB\s*2x1,5)",
                re.IGNORECASE,
            ),
        ),
        (
            "garbled_row1",
            re.compile(
                rf"(?:^|\s)(?:1\s+)?(13{_SIZE_X}4ок\s*\(N,?\s*PE\)-0,66\S*)",
                re.IGNORECASE,
            ),
        ),
        (
            "garbled_row1_bare",
            re.compile(
                rf"(?:^|\s)(?:1\s+)?(3{_SIZE_X}4ок\s*\(N,?\s*PE\)-0,66\S*)",
                re.IGNORECASE,
            ),
        ),
        (
            "garbled_wire",
            re.compile(
                rf"(?:^|\s)2\s+(ПВСнг\(А\)-LS\s*3{_SIZE_X}?2,50\S*)",
                re.IGNORECASE,
            ),
        ),
        (
            "garbled_apuv",
            re.compile(
                rf"(?:^|\s)3\s+(АПуВ\s*1{_SIZE_X}?6\S*)",
                re.IGNORECASE,
            ),
        ),
        (
            "garbled_pbgbv",
            re.compile(
                rf"(?:^|\s)4\s+(ПБГВВ\s*2{_SIZE_X}?1,5\S*)",
                re.IGNORECASE,
            ),
        ),
    )

    for _kind, pattern in patterns:
        for m in pattern.finditer(text):
            raw = m.group(1) if m.lastindex else m.group(0)
            cleaned = _clean_periodic_mark(raw)
            if len(cleaned) < 4:
                continue
            tail = text[m.end() : m.end() + 60]
            doc = extract_document_from_text(m.group(0) + " " + tail)
            found.append((cleaned, m.start(1), m.end(1), doc))

    ranked = sorted(found, key=lambda item: (_row_sort_key(item[0]), -len(item[0]), item[1]))
    seen: set[str] = set()
    canonical_keys: list[str] = []
    matches: list[CableMarkMatch] = []
    for mark, start, end, doc in ranked:
        key = _canonical_periodic_mark(mark)
        if key in seen:
            continue
        if any(key != other and key in other for other in canonical_keys):
            continue
        seen.add(key)
        canonical_keys.append(key)
        snippet = text[max(0, start - 80) : min(len(text), end + 80)]
        matches.append(
            CableMarkMatch(
                mark=mark,
                context=re.sub(r"\s+", " ", snippet).strip(),
                document=doc,
            )
        )

    return matches