"""
pdf_extractor.py — извлечение данных из входящих заявок (PDF, Word .docx).

Текстовые PDF: pdfplumber.
Сканы (картинки без текстового слоя): OCR через pytesseract или easyocr.
Поиск марок — по структуре строки (бренд + «NхM»), без списка брендов.
Организации — через organization_extractor (заказчик, производитель).
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from typing import Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from ..config import OCR_CACHE_DIR
from ..parsing.cable_mark_parser import extract_document_from_text, fix_ocr_document_text
from ..assistant.mark_corrector import suggest_mark_correction
from ..models import CableMarkMatch, PdfExtractionResult
from .ocr_text_normalizer import normalize_ocr_text
from .organization_extractor import (
    extract_organizations,
    finalize_organizations,
    pick_customer_name,
    pick_manufacturer_name,
)

logger = logging.getLogger(__name__)

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None  # type: ignore[assignment]

# --- Паттерны марки (структурные, без whitelist брендов) ---

_SIZE_PART = (
    r"\d+\s*[зЗпП]?\s*[хx]\s*"
    r"(?:[\d.,\(\)]+|[а-яёa-zA-Z]{1,6})"
    r"(?:\s*[хx]\s*[\d.,\(\)]+)*"
    r"(?:[а-яёa-zA-Z\-\(\),\d/]*)"
    r"(?:\s*\([^)]+\))?"
    r"(?:-\d+[.,]?\d*)?"
)

_NAME_PART = (
    r"(?:ККЗ\s+МК\s+)?"
    r"[А-ЯЁA-Z][А-ЯЁа-яёA-Za-z0-9\-\(\)/]+"
    r"(?:[\-–/][А-ЯЁа-яёA-Za-z0-9\(\)/]+)*"
)

# Размер: 2х2, 2x2x0,52, 4x2x0.52 (LAN-кабель)
_SIZE_PART_LATIN = (
    r"\d+\s*x\s*\d+"
    r"(?:\s*x\s*[\d.,]+)?"
)

# СПЕЦЛАН / SPECLAN / CMELVIAH (OCR) F/UTP … 2x2x0,52
_SPECLAN_BRAND = r"(?:СПЕЦЛАН|SPECLAN|CMELVIAH|CMELAN)"
_SPECLAN_FIRE = r"(?:нг|ur|Hr|hr|ng|Нг)\s*\(\s*A\s*\)"
_SPECLAN_MARK_PATTERN = re.compile(
    r"(?:\d+\.\s*)?"
    rf"({_SPECLAN_BRAND}\s+(?:SF?/)?UTP\s+Cat\s+5\w\s+ZH\s+{_SPECLAN_FIRE}-HF\s+\d+\s*x\s*\d+(?:\s*x\s*[\d.,]+)?)",
    re.IGNORECASE,
)

# Нумерованный список марок в письме (кириллица + латинский OCR)
_LETTER_MARKS_BLOCK = re.compile(
    r"(?:марк[аи]|mapkax?)\s+(?:кабел[ья]|kabena?)[:\s]+"
    r"(.+?)(?=Последующ|Nocnegy|С\s+уважением|Суважением|$)",
    re.IGNORECASE | re.DOTALL,
)
_LETTER_MARK_ITEM = re.compile(
    r"\d+\.\s*"
    rf"({_SPECLAN_BRAND}\s+.+?)"
    r"(?:\s+(?:ТУ|TU|Ty)\s*\d+\.[КкKk]\d{2,3}-\d{3}-\d{4})?"
    r"(?=\s+(?:В\s+количестве|KonuyectBe)|;|\d+\.\s+(?:СПЕЦ|SPECLAN|CMEL)|\d+\.\s+[А-ЯЁA-Z]|$)",
    re.IGNORECASE,
)
_TU_TAIL_PATTERN = re.compile(
    r"ТУ\s*\d+\.[КкKk]\d{2,3}-\d{3}-\d{4}",
    re.IGNORECASE,
)

_MARK_PATTERN = re.compile(
    rf"{_NAME_PART}\s+{_SIZE_PART}",
    re.IGNORECASE,
)

# КГРвЭСТ 3*35+16/3в+3*2,5 - 1140 (направления СЕРК, звёздочная запись жил)
_STAR_CORE_MARK_PATTERN = re.compile(
    r"(КГ[А-ЯЁа-яёA-Za-z]+\s+"
    r"\d+\*[\d.,]+"
    r"(?:\+[\d\*\/вВa-zA-Z.,]+)*"
    r"(?:\s*-\s*1140)?)",
    re.IGNORECASE,
)

# FLEXICORE (заявка Флексикор, таблица приложения)
_FLEXICORE_FIRE = r"нг\([AaАа]\)"
_FLEXICORE_MARK_PATTERN = re.compile(
    r"(FLEXICORE(?:®)?\s+"
    r"(?:"
    rf"FLAT\s+{_FLEXICORE_FIRE}-LS"
    r"|Li(?:YY|YCY)"
    r"|(?:\d+\s+)?(?:H|CH|CY)(?:\s+{_FLEXICORE_FIRE}-(?:LS|HF))?"
    r"(?:\s+\d+[.,]?\d*\s*/\s*\d+\s*кВ)?"
    r"|100(?:\s+0,6/1\s*кВ)?(?:\s+{_FLEXICORE_FIRE}-LS(?:\s+0,6/1\s*кВ)?)?"
    r"|110(?:\s+{_FLEXICORE_FIRE}-LS)?"
    r"))",
    re.IGNORECASE,
)
_FLEXICORE_TABLE_LINE = re.compile(
    r"(FLEXICORE(?:®)?\s+[^\n|]{2,90}?)(?=\s*\||\s*ТУ|\n|$)",
    re.IGNORECASE,
)
_H07RN_MARK_PATTERN = re.compile(r"(H07RN-F\s+RU)", re.IGNORECASE)

# VicabFLEX (латиница, направления в ИЛ)
_VICABFLEX_FIRE = r"нг\([AaАа]\)"
_VICABFLEX_MARK_PATTERN = re.compile(
    r"(VicabFLEX\s+"
    r"\d+\s+"
    r"(?:CY|СУ)\s+"
    r"(?:"
    rf"{_VICABFLEX_FIRE}-LS\s+\d+\s*[xх]\s*[\d.,]+(?:\s*\d+/\d+\s*В)?"
    r"|"
    r"\d+[.,]?\d*\s*/\s*\d+\s*кВ\s+\d+\s*[xх]\s*[\d.,]+(?:\s*\d+/\d+\s*В)?"
    r"))",
    re.IGNORECASE,
)

# Контекстный поиск после «марки:» / «марка»
_AFTER_MARKI_PATTERN = re.compile(
    rf"(?:кабел[ья]\s+)?(?:силовой\s+)?марк[аи]\s*:?\s*"
    rf"({_NAME_PART}\s+{_SIZE_PART})",
    re.IGNORECASE,
)

# Провод/кабель «марки X» (включая OCR «ПровоА», «Nposoa Mapkn»)
_PRODUCT_MARK_PATTERN = re.compile(
    rf"(?:Прово\w*|Кабел\w*|Mapkn\w*)[^\n]{{0,50}}?марк[аи]\s*:?\s*"
    rf"({_NAME_PART}\s+{_SIZE_PART})",
    re.IGNORECASE,
)

_REJECT_PREFIXES = re.compile(
    r"^(?:солнечного|излучения|воздействию|стойкость|требования|наименование|"
    r"марка|образец|№|п\.|пункт|гост|ту|нд)\b",
    re.IGNORECASE,
)

DEFAULT_OCR_DPI = 200
SCAN_OCR_DPI = 300

_EASYOCR_READER = None


def _require_pdfplumber() -> None:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber не установлен. Выполни: pip install pdfplumber")


def _normalize_text(text: str) -> str:
    """Приводит текст PDF/OCR к удобному для поиска виду."""
    text = text.replace("\xa0", " ")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"-\s*\n\s*", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_text_for_marks(text: str) -> str:
    """
    Нормализация для поиска марок.

    Сохраняет латинское «x» в размерах (2x2x0,52, Cat 5e) и в F/UTP.
    Кириллическое «х» унифицирует в «x» для единого паттерна.
    """
    text = _normalize_text(text)
    text = text.replace("×", "x").replace("Х", "x").replace("х", "x")
    return text


def _fix_speclan_letter_ocr(text: str) -> str:
    """Правки OCR в гарантийных письмах (латиница вместо кириллицы)."""
    text = re.sub(
        r"\b(?:CMELVIAH|CMELAN|SPECLAN|Cneu\w*lan|Sneu\w*lan)\b",
        "СПЕЦЛАН",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bMapkax?\s+Kabena?\b",
        "Марках кабеля",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bKonuyectBe\b", "В количестве", text, flags=re.IGNORECASE)
    text = re.sub(
        r"ZH\s+(?:ur|Hr|hr|ng|нr|Нг)\s*\(\s*A\s*\)",
        "ZH нг(А)",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"TapaHTuiHoe\s+nucbmMo",
        "Гарантийное письмо",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Mpocum\s+Bac\s+nprovectu",
        "Просим Вас провести",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"TeHepanbHomy\s+AnpekTopy",
        "Генеральному директору",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bOOO\s+HNN\b", "ООО НПП", text, flags=re.IGNORECASE)
    text = re.sub(r"Cneukabenl?", "Спецкабель", text, flags=re.IGNORECASE)
    text = re.sub(r"Kabenb-TecT", "Кабель-Тест", text, flags=re.IGNORECASE)
    text = re.sub(r"\bYa\.\s+", "ул. ", text, flags=re.IGNORECASE)
    return text


def _fix_periodic_letter_ocr(text: str) -> str:
    """Правки OCR в письмах на периодические испытания (таблица марок)."""
    text = re.sub(
        r"N?Mpocum\s+Bac\s+nprovectm?",
        "Просим Вас провести",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"TeEHEPAAbHOMY\s+ANPeKTOPy", "Генеральному директору", text, flags=re.IGNORECASE)
    text = re.sub(r"KaayxKckni\s+KaGeAbHbIN\s+3GB0A", "Калужский кабельный завод", text, flags=re.IGNORECASE)
    text = re.sub(
        r"Nnepuoauyeckie\s+UCNblITAHMA",
        "периодические испытания",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bBBI-MHr\(A\)", "ВВГнг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBBI-", "ВВГ-", text, flags=re.IGNORECASE)
    text = re.sub(r"ББР-Мнг\(А\)", "ВВГ-Пнг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"\bББР-", "ВВГ-П", text, flags=re.IGNORECASE)
    text = re.sub(r"3[хx]2,50К", "3х2,5ок", text, flags=re.IGNORECASE)
    text = re.sub(r"\(N,\s*РЕ\)", "(N, PE)", text, flags=re.IGNORECASE)
    text = re.sub(r"--0,66", "-0,66", text)
    text = re.sub(r"NBCur\(A\)-LS", "ПВСнг(А)-LS", text, flags=re.IGNORECASE)
    text = re.sub(r"МБСнг\(А\)\}", "ПВСнг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"\bМБСнг", "ПВСнг", text, flags=re.IGNORECASE)
    text = re.sub(r"\bAllyB\b", "АПуВ", text, flags=re.IGNORECASE)
    text = re.sub(r"FIБББ", "ПБГВВ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNBIBB\b", "ПБГВВ", text, flags=re.IGNORECASE)
    text = re.sub(r"Мул\s+Бгат\s*\(А\)", "ПуПВнг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"LSLТ[хx]", "LSLTx", text)
    text = re.sub(r"3[хx]1\.5", "3х1,5", text, flags=re.IGNORECASE)
    text = re.sub(r"3x40K", "3х4ок", text, flags=re.IGNORECASE)
    text = re.sub(r"Nposoa\s+Mapkn\w*", "Провод марки", text, flags=re.IGNORECASE)
    text = re.sub(r"Ka6eAb\s+CHACBON\s+MAPK:", "Кабель силовой марки:", text, flags=re.IGNORECASE)
    text = re.sub(
        r"Nроснм\s+Бас\s+нросестн",
        "Просим Вас провести",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"нерноануескн\w*", "периодические", text, flags=re.IGNORECASE)
    return text


def _fix_flexicore_ocr(text: str) -> str:
    """Правки OCR в заявках FLEXICORE."""
    text = re.sub(r"FL[Ee3][XХx][I1l]CORE", "FLEXICORE", text, flags=re.IGNORECASE)
    text = re.sub(r"FLEX1CORE", "FLEXICORE", text, flags=re.IGNORECASE)
    text = re.sub(r"нг\s*\(\s*A\s*\)", "нг(A)", text, flags=re.IGNORECASE)
    return text


def _fix_vicab_direction_ocr(text: str) -> str:
    """Правки OCR в направлениях СЕРК (VicabFLEX, CY, кВ)."""
    text = re.sub(
        r"V[иiI][сc]аб[A-Za-zА-Яа-яЁё]{0,10}",
        "VicabFLEX",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"VicabFLEx", "VicabFLEX", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(VicabFLEX\s+\d+)\s+СУ\b",
        r"\1 CY",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"0,6/1\s+КБ\s+", "0,6/1 кВ ", text, flags=re.IGNORECASE)
    text = re.sub(r"600/1000\s+Б\b", "600/1000В", text, flags=re.IGNORECASE)
    text = re.sub(r"300/500\s+Б\b", "300/500 В", text, flags=re.IGNORECASE)
    text = re.sub(r"нг\s*\(\s*A\s*\)", "нг(A)", text, flags=re.IGNORECASE)
    return text


def _fix_latin_brand_ocr(text: str) -> str:
    return _fix_flexicore_ocr(_fix_vicab_direction_ocr(text))


def _fix_ocr_confusables(text: str) -> str:
    """Исправляет типичные OCR-ошибки перед поиском марок и ТУ."""
    text = _fix_latin_brand_ocr(text)
    text = _fix_speclan_letter_ocr(text)
    text = _fix_periodic_letter_ocr(text)
    return normalize_ocr_text(text)


def is_plausible_mark(mark: str) -> bool:
    """Отсекает явные ложные срабатывания из «рваного» текста PDF/OCR."""
    if re.search(r"\d{4,},\d{2}", mark):
        return False
    if len(re.findall(r"\d{1,3}(?:\s\d{3})*,\d{2}", mark)) >= 2:
        return False
    if re.search(r"\d{2}\.\d{4}", mark):
        return False
    if _REJECT_PREFIXES.search(mark):
        return False
    if re.match(r"^нг\(", mark, re.IGNORECASE):
        return False
    if re.match(r"^кВ\s*\d", mark, re.IGNORECASE):
        return False
    if not re.match(r"^[А-ЯЁA-Z]", mark):
        return False
    if not re.match(
        r"^(?:ККЗ\s+МК\s+|СПЕЦЛАН\s+|VicabFLEX\s+|КГ[А-ЯЁа-яё]|[А-ЯЁA-Z])",
        mark,
        re.IGNORECASE,
    ):
        return False
    has_cyr_size = re.search(
        r"\d+\s*[зЗпП]?\s*[хx]\s*(?:[\d.,]|[а-яёa-zA-Z])", mark, re.IGNORECASE
    )
    has_lan_size = re.search(_SIZE_PART_LATIN, mark, re.IGNORECASE)
    has_star_size = re.search(r"\d+\*[\d.,]", mark)
    is_latin_brand = re.match(r"^(?:FLEXICORE|VicabFLEX|H07RN-F)", mark, re.IGNORECASE)
    if not has_cyr_size and not has_lan_size and not has_star_size and not is_latin_brand:
        return False
    name = re.split(r"\s+\d", mark, maxsplit=1)[0]
    if len(name) > 100 or len(name) < 3:
        return False
    return True


def _clean_mark(raw: str) -> str:
    """Убирает хвостовой мусор из кандидата в марку и правит OCR-латиницу."""
    mark = raw.strip(" .,;:\n")
    mark = re.sub(
        rf"^(.+?{_SIZE_PART})\s+м\s+\d.*",
        r"\1",
        mark,
        flags=re.IGNORECASE,
    )
    mark = re.sub(r"\s+Упаковка.*$", "", mark, flags=re.IGNORECASE)
    mark = re.sub(
        r"\s+(?:Прово\w*|Кабел\w*|марк[аи]|ТУ|ГОСТ|СТО).*$",
        "",
        mark,
        flags=re.IGNORECASE,
    )
    if mark.upper().startswith("СПЕЦЛАН"):
        mark = re.sub(r"\s+В\s+количестве.*$", "", mark, flags=re.IGNORECASE)
    if mark.upper().startswith("VICABFLEX"):
        mark = re.sub(r"нг\([Аа]\)", "нг(A)", mark, flags=re.IGNORECASE)
        mark = re.sub(r"\bСУ\b", "CY", mark, flags=re.IGNORECASE)
        mark = re.sub(r"(\d)кВ", r"\1 кВ", mark, flags=re.IGNORECASE)
        return mark.strip()
    if mark.upper().startswith("FLEXICORE") or mark.upper().startswith("H07RN"):
        mark = mark.replace("®", "")
        mark = re.sub(r"нг\([Аа]\)", "нг(A)", mark, flags=re.IGNORECASE)
        mark = re.sub(r"\s+", " ", mark).strip()
        return mark
    if re.match(r"^КГ[А-ЯЁа-яё]", mark):
        return mark.strip()
    suggestion = suggest_mark_correction(mark.strip())
    return suggestion.suggested


def _context_snippet(text: str, start: int, end: int, radius: int = 120) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = text[left:right].strip()
    return re.sub(r"\s+", " ", snippet)


def _add_match(
    matches: list[CableMarkMatch],
    seen: set[str],
    mark: str,
    text: str,
    start: int,
    end: int,
    *,
    document: str | None = None,
) -> None:
    mark = _clean_mark(mark)
    key = mark.lower()
    if len(mark) < 5 or key in seen or not is_plausible_mark(mark):
        return
    seen.add(key)
    context = _context_snippet(text, start, end, radius=180)
    doc = document or extract_document_from_text(context)
    matches.append(
        CableMarkMatch(
            mark=mark,
            context=context,
            document=doc,
        )
    )


def _find_letter_list_marks(text: str) -> list[tuple[str, int, int, str | None]]:
    """Марки из нумерованного списка в гарантийном/сопроводительном письме."""
    found: list[tuple[str, int, int, str | None]] = []
    block = _LETTER_MARKS_BLOCK.search(text)
    search_in = block.group(1) if block else text
    base_offset = block.start(1) if block else 0

    for m in _LETTER_MARK_ITEM.finditer(search_in):
        mark = m.group(1).strip()
        if not re.match(r"^(?:СПЕЦЛАН|SPECLAN|CMEL)", mark, re.IGNORECASE):
            continue
        doc = m.group(2).strip() if m.lastindex and m.lastindex >= 2 and m.group(2) else None
        if not doc:
            tail = search_in[m.end() : m.end() + 80]
            tu_m = _TU_TAIL_PATTERN.search(tail)
            doc = tu_m.group(0) if tu_m else None
        if doc:
            doc = extract_document_from_text(doc) or doc
        found.append((mark, base_offset + m.start(1), base_offset + m.end(1), doc))

    if not found:
        for m in _SPECLAN_MARK_PATTERN.finditer(text):
            tail = text[m.end() : m.end() + 80]
            tu_m = _TU_TAIL_PATTERN.search(tail)
            doc = extract_document_from_text(tu_m.group(0)) if tu_m else None
            found.append((m.group(1), m.start(1), m.end(1), doc))

    return found


def _dedupe_cable_matches(items: list[CableMarkMatch]) -> list[CableMarkMatch]:
    seen: set[str] = set()
    out: list[CableMarkMatch] = []
    for m in items:
        fixed = _clean_mark(m.mark)
        key = fixed.lower()
        if fixed and key not in seen:
            seen.add(key)
            out.append(
                CableMarkMatch(
                    mark=fixed,
                    context=m.context,
                    document=m.document,
                    requirements_raw=m.requirements_raw,
                )
            )
    return out


def _extract_marks_from_family(text: str, family_id: str) -> list[CableMarkMatch]:
    """Извлекает марки через YAML-семейство, только при уверенном совпадении."""
    from .families.registry import DocumentFamily, get_family_registry

    registry = get_family_registry()
    family: DocumentFamily | None = registry.get(family_id)
    if family is None or not family.is_confident_match(text):
        return []

    if family_id == "kaluga_periodic_v1":
        from .periodic_letter_extractor import extract_marks_from_periodic_letter

        periodic = extract_marks_from_periodic_letter(text)
        cleaned = _dedupe_cable_matches(periodic)
        if len(cleaned) >= family.min_marks_threshold:
            return cleaned
        return []

    matches: list[CableMarkMatch] = []
    seen: set[str] = set()
    for _kind, pattern in family.mark_patterns:
        for m in pattern.finditer(text):
            raw = m.group(1) if m.lastindex else m.group(0)
            _add_match(matches, seen, raw, text, m.start(), m.end())

    if family_id == "speclan_letter_v1" and len(matches) < family.min_marks_threshold:
        for mark, start, end, doc in _find_letter_list_marks(text):
            _add_match(matches, seen, mark, text, start, end, document=doc)

    if len(matches) >= family.min_marks_threshold:
        return matches
    return []


def find_cable_marks(text: str) -> list[CableMarkMatch]:
    """
    Ищет марки кабелей по структурному паттерну «название + NхM».

    Не использует список брендов — любая строка нужной формы.
    Семейства YAML (Калуга, Спецкабель) — только при score ≥ confidence_threshold.
    """
    base = _normalize_text_for_marks(text)
    if not base:
        return []

    seen: set[str] = set()
    matches: list[CableMarkMatch] = []

    # Латиница и КГ* — до normalize_ocr_text (он портит FLEXICORE/VicabFLEX)
    latin_safe = _fix_latin_brand_ocr(base)
    for pattern in (
        _FLEXICORE_MARK_PATTERN,
        _FLEXICORE_TABLE_LINE,
        _H07RN_MARK_PATTERN,
        _VICABFLEX_MARK_PATTERN,
        _STAR_CORE_MARK_PATTERN,
    ):
        for m in pattern.finditer(latin_safe):
            raw = m.group(1) if m.lastindex else m.group(0)
            _add_match(matches, seen, raw, latin_safe, m.start(), m.end())

    normalized = _fix_ocr_confusables(base)

    from .families.registry import get_family_registry

    family = get_family_registry().detect_best(normalized)
    if family is not None:
        family_marks = _extract_marks_from_family(normalized, family.id)
        if family_marks:
            return _dedupe_cable_matches(matches + family_marks)

    for mark, start, end, doc in _find_letter_list_marks(normalized):
        _add_match(matches, seen, mark, normalized, start, end, document=doc)

    for pattern in (
        _SPECLAN_MARK_PATTERN,
        _AFTER_MARKI_PATTERN,
        _PRODUCT_MARK_PATTERN,
        _MARK_PATTERN,
    ):
        for m in pattern.finditer(normalized):
            raw = m.group(1) if m.lastindex else m.group(0)
            _add_match(matches, seen, raw, normalized, m.start(), m.end())

    return matches


def resolve_ocr_engine() -> Literal["tesseract", "easyocr", "none"]:
    """Какой OCR-движок будет использован для сканов (tesseract приоритетнее)."""
    if _find_tesseract():
        return "tesseract"
    try:
        import easyocr  # noqa: F401
    except ImportError:
        return "none"
    return "easyocr"


def _pdf_cache_fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _ocr_cache_path(path: Path, dpi: int, engine: str, *, preprocess: str | None = None) -> Path:
    fingerprint = _pdf_cache_fingerprint(path)
    safe_stem = re.sub(r"[^\w\-.]+", "_", path.stem)[:48]
    pre_tag = f"_pre{preprocess}" if preprocess else ""
    return OCR_CACHE_DIR / f"{safe_stem}_{fingerprint}_dpi{dpi}_{engine}{pre_tag}.txt"


def _read_ocr_cache(path: Path, dpi: int, engine: str, *, preprocess: str | None = None) -> str | None:
    cache_path = _ocr_cache_path(path, dpi, engine, preprocess=preprocess)
    if not cache_path.is_file():
        return None
    text = cache_path.read_text(encoding="utf-8")
    return text if text.strip() else None


def _write_ocr_cache(
    path: Path, dpi: int, engine: str, text: str, *, preprocess: str | None = None
) -> None:
    if not text.strip():
        return
    cache_path = _ocr_cache_path(path, dpi, engine, preprocess=preprocess)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")


def clear_ocr_cache() -> int:
    """Удаляет файлы кэша OCR. Возвращает число удалённых файлов."""
    if not OCR_CACHE_DIR.is_dir():
        return 0
    removed = 0
    for cache_file in OCR_CACHE_DIR.glob("*.txt"):
        cache_file.unlink(missing_ok=True)
        removed += 1
    return removed


def _get_easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        _EASYOCR_READER = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _EASYOCR_READER


def _find_tesseract() -> str | None:
    """Ищет tesseract.exe в PATH и типичных путях Windows."""
    found = shutil.which("tesseract")
    if found:
        return found
    project_root = Path(__file__).resolve().parents[2]
    for candidate in (
        project_root / "tools" / "Tesseract-OCR" / "tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        path = Path(candidate)
        if path.exists():
            return str(path)
    return None


def _render_pages(pdf_path: Path, dpi: int = DEFAULT_OCR_DPI) -> list:
    """Рендерит страницы PDF в PIL.Image через PyMuPDF."""
    import fitz
    from PIL import Image

    doc = fitz.open(str(pdf_path))
    images: list = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    for page in doc:
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        images.append(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
    doc.close()
    return images


def _resolve_preprocess_tag(use_preprocess: bool) -> str | None:
    if not use_preprocess:
        return None
    from .ocr.preprocess import PREPROCESS_VERSION, is_cv_available

    return PREPROCESS_VERSION if is_cv_available() else None


def _ocr_image_tesseract(image, pytesseract, *, use_preprocess: bool = True) -> str:
    # rus первичен — кириллица в марках; eng для Cat/UTP в LAN-кабеле
    if use_preprocess:
        from .ocr.preprocess import is_cv_available, preprocess_for_ocr

        if is_cv_available():
            image = preprocess_for_ocr(image)
    config = "--psm 6 --oem 1"
    return pytesseract.image_to_string(image, lang="rus+eng", config=config)


def _ocr_with_tesseract(
    pdf_path: Path, dpi: int = DEFAULT_OCR_DPI, *, use_preprocess: bool = True
) -> str:
    import pytesseract

    tesseract_cmd = _find_tesseract()
    if not tesseract_cmd:
        raise RuntimeError(
            "Tesseract OCR не найден. Установи: "
            "https://github.com/UB-Mannheim/tesseract/wiki "
            "(нужен язык rus)."
        )
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    images = _render_pages(pdf_path, dpi=dpi)
    if len(images) == 1:
        text = _ocr_image_tesseract(images[0], pytesseract, use_preprocess=use_preprocess)
        return text.strip()

    parts: list[str] = [""] * len(images)
    with ThreadPoolExecutor(max_workers=min(4, len(images))) as pool:
        futures = {
            pool.submit(_ocr_image_tesseract, img, pytesseract, use_preprocess=use_preprocess): idx
            for idx, img in enumerate(images)
        }
        for future in as_completed(futures):
            idx = futures[future]
            parts[idx] = future.result().strip()

    return "\n\n".join(p for p in parts if p)


def _ocr_with_easyocr(pdf_path: Path, dpi: int = DEFAULT_OCR_DPI) -> str:
    import numpy as np

    reader = _get_easyocr_reader()
    parts: list[str] = []
    for image in _render_pages(pdf_path, dpi=dpi):
        lines = reader.readtext(np.array(image), detail=0, paragraph=True)
        if lines:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def ocr_pdf(
    pdf_path: Path | str,
    dpi: int = DEFAULT_OCR_DPI,
    *,
    use_cache: bool = True,
    use_preprocess: bool = True,
) -> str:
    """
    Распознаёт текст со скана. Сначала tesseract, при недоступности — easyocr.

    Результат кэшируется в ``data/ocr_cache/`` по отпечатку файла, DPI, движку
    и версии препроцессинга (OpenCV v1 для сканов).
    """
    path = Path(pdf_path)
    engine = resolve_ocr_engine()
    preprocess_tag = _resolve_preprocess_tag(use_preprocess) if engine == "tesseract" else None

    if use_cache and engine != "none":
        cached = _read_ocr_cache(path, dpi, engine, preprocess=preprocess_tag)
        if cached is not None:
            logger.debug(
                "OCR cache hit: %s (%s, dpi=%d, pre=%s)",
                path.name,
                engine,
                dpi,
                preprocess_tag,
            )
            return normalize_ocr_text(cached)

    text = ""
    if engine == "tesseract":
        try:
            text = _ocr_with_tesseract(path, dpi=dpi, use_preprocess=use_preprocess)
        except Exception as exc:
            logger.warning("Tesseract OCR failed: %s", exc)
            engine = "easyocr"
            preprocess_tag = None
            if use_cache:
                cached = _read_ocr_cache(path, dpi, engine)
                if cached is not None:
                    return cached

    if not text.strip():
        try:
            text = _ocr_with_easyocr(path, dpi=dpi)
            engine = "easyocr"
            preprocess_tag = None
        except ImportError as exc:
            raise RuntimeError(
                "Для сканов нужен OCR. Установи Tesseract (rus) или: pip install easyocr"
            ) from exc

    if text.strip():
        text = normalize_ocr_text(text)

    if use_cache and text.strip():
        _write_ocr_cache(path, dpi, engine, text, preprocess=preprocess_tag)
    return text


def extract_text(pdf_path: Path | str, *, use_ocr: bool = False) -> str:
    """Извлекает текст: pdfplumber, для сканов — с OCR если use_ocr=True."""
    _require_pdfplumber()
    path = Path(pdf_path)
    parts: list[str] = []

    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            page_text = page.extract_text() or ""
            if page_text:
                parts.append(page_text)

    text = "\n\n".join(parts)
    if not text.strip() and use_ocr:
        text = ocr_pdf(path)
    return text


def extract_tables(pdf_path: Path | str) -> list[list[list[str]]]:
    """Извлекает таблицы. Каждая ячейка — строка (пустые → '')."""
    _require_pdfplumber()
    path = Path(pdf_path)
    tables: list[list[list[str]]] = []

    with pdfplumber.open(path) as doc:
        for page in doc.pages:
            for table in page.extract_tables() or []:
                cleaned = [
                    [str(cell).strip() if cell is not None else "" for cell in row]
                    for row in table
                ]
                if any(any(cell for cell in row) for row in cleaned):
                    tables.append(cleaned)

    return tables


def _tables_to_text(tables: list[list[list[str]]]) -> str:
    return "\n".join(" ".join(cell for cell in row if cell) for table in tables for row in table)


def _resolve_cable_marks(
    text: str,
    tables: list[list[list[str]]],
) -> list[CableMarkMatch]:
    """
    Марки кабелей: table-first для направлений, иначе regex по тексту.

    Таблица направления приоритетнее плоского текста PDF.
    """
    if tables:
        from .direction_table_extractor import extract_marks_from_tables

        table_marks = extract_marks_from_tables(tables)
        if table_marks:
            return table_marks

    search_text = text
    if tables:
        search_text = f"{text}\n{_tables_to_text(tables)}".strip()
    return find_cable_marks(search_text)


def _cyrillic_letter_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cyrillic = sum(1 for c in letters if "\u0400" <= c <= "\u04FF")
    return cyrillic / len(letters)


def _pdf_page_stats(pdf_path: Path) -> tuple[int, bool, str]:
    """page_count, has_images, joined pdfplumber text."""
    _require_pdfplumber()
    with pdfplumber.open(pdf_path) as doc:
        page_count = len(doc.pages)
        has_images = any(page.images for page in doc.pages)
        parts = [page.extract_text() or "" for page in doc.pages]
        return page_count, has_images, "\n\n".join(parts).strip()


def _needs_ocr_fallback(text: str, *, has_images: bool) -> bool:
    """
    Текстовый слой есть, но нечитаем (латиница вместо кириллицы) — нужен OCR.

    Типично для PDF со сканом-вложением и мусорным pseudo-text layer.
    """
    if not has_images or not text.strip():
        return False
    return _cyrillic_letter_ratio(text) < 0.2


def _detect_scanned(pdf_path: Path) -> tuple[bool, int]:
    """True, если PDF похож на скан (есть изображения, но нет текста)."""
    page_count, has_images, text = _pdf_page_stats(pdf_path)
    is_scanned = page_count > 0 and not text and has_images
    return is_scanned, page_count


def build_search_text(text: str, tables: list[list[list[str]]] | None = None) -> str:
    """Текст заявки + плоское представление таблиц для поиска org/марок."""
    if not tables:
        return text
    return f"{text}\n{_tables_to_text(tables)}".strip()


def extract_from_pdf(
    pdf_path: Path | str,
    *,
    use_ocr: bool = True,
    ocr_dpi: int = DEFAULT_OCR_DPI,
    use_ocr_cache: bool = True,
) -> PdfExtractionResult:
    """
    Полное извлечение: текст, таблицы, марки кабелей, метаданные.

    Для сканов при use_ocr=True автоматически запускает OCR.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF не найден: {path}")

    is_scanned, page_count = _detect_scanned(path)
    _page_count, has_images, plumber_text = _pdf_page_stats(path)
    ocr_used = False
    tables: list[list[list[str]]] = []

    table_ocr_text = ""
    use_ocr_path = is_scanned or (
        use_ocr and has_images and _needs_ocr_fallback(plumber_text, has_images=has_images)
    )

    if use_ocr_path:
        # True scans — 300 DPI; garbled pseudo-text layer — default DPI (200 часто лучше).
        scan_dpi = max(ocr_dpi, SCAN_OCR_DPI) if is_scanned else ocr_dpi
        text = ocr_pdf(path, dpi=scan_dpi, use_cache=use_ocr_cache, use_preprocess=use_ocr)
        ocr_used = True
        if not is_scanned:
            logger.info(
                "PDF %s: pseudo-text layer (cyr=%.0f%%) — OCR fallback",
                path.name,
                _cyrillic_letter_ratio(plumber_text) * 100,
            )
        if not use_ocr:
            logger.warning("PDF %s: скан — OCR включён принудительно", path.name)
        if is_scanned:
            try:
                from .ocr.table import ocr_tables_from_pdf, tables_text_from_results

                table_results = ocr_tables_from_pdf(path, dpi=scan_dpi)
                table_ocr_text = tables_text_from_results(table_results)
                if table_ocr_text:
                    tables = [result.rows for result in table_results if result.rows]
                    text = f"{text}\n\n{table_ocr_text}".strip()
                    logger.info(
                        "PDF %s: table OCR added %d chars from %d page(s)",
                        path.name,
                        len(table_ocr_text),
                        len(table_results),
                    )
            except Exception as exc:
                logger.debug("Table OCR skipped for %s: %s", path.name, exc)
    else:
        text = extract_text(path)
        tables = extract_tables(path)

    search_text = build_search_text(text, tables)

    cable_marks = _resolve_cable_marks(text, tables)
    organizations = finalize_organizations(extract_organizations(search_text), search_text)

    logger.info(
        "PDF %s: pages=%d, text=%d chars, tables=%d, marks=%d, orgs=%d, scanned=%s, ocr=%s",
        path.name,
        page_count,
        len(text),
        len(tables),
        len(cable_marks),
        len(organizations),
        is_scanned,
        ocr_used,
    )

    return PdfExtractionResult(
        source_path=str(path.resolve()),
        source_type="pdf",
        page_count=page_count,
        text=text,
        tables=tables,
        cable_marks=cable_marks,
        organizations=organizations,
        customer_name=pick_customer_name(organizations),
        manufacturer_name=pick_manufacturer_name(organizations),
        is_scanned=is_scanned,
        ocr_used=ocr_used,
        extracted_at=datetime.now(),
    )


def extract_text_from_docx(docx_path: Path | str) -> str:
    """Извлекает текст из Word-документа (.docx)."""
    from docx import Document

    path = Path(docx_path)
    doc = Document(str(path))
    parts: list[str] = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text.strip())
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" ".join(cells))
    return "\n".join(parts)


def extract_tables_from_docx(docx_path: Path | str) -> list[list[list[str]]]:
    """Таблицы Word в том же формате, что pdfplumber — для table-first направлений."""
    from docx import Document

    path = Path(docx_path)
    doc = Document(str(path))
    tables: list[list[list[str]]] = []
    for table in doc.tables:
        cleaned = [
            [cell.text.strip() for cell in row.cells]
            for row in table.rows
        ]
        if any(any(cell for cell in row) for row in cleaned):
            tables.append(cleaned)
    return tables


def _build_extraction_result(
    *,
    source_path: Path,
    source_type: Literal["pdf", "docx"],
    text: str,
    page_count: int = 0,
    tables: list[list[list[str]]] | None = None,
    is_scanned: bool = False,
    ocr_used: bool = False,
) -> PdfExtractionResult:
    """Собирает результат: марки + организации из текста заявки."""
    search_text = build_search_text(text, tables)
    organizations = finalize_organizations(extract_organizations(search_text), search_text)
    return PdfExtractionResult(
        source_path=str(source_path.resolve()),
        source_type=source_type,
        page_count=page_count,
        text=text,
        tables=tables or [],
        cable_marks=_resolve_cable_marks(text, tables or []),
        organizations=organizations,
        customer_name=pick_customer_name(organizations),
        manufacturer_name=pick_manufacturer_name(organizations),
        is_scanned=is_scanned,
        ocr_used=ocr_used,
        extracted_at=datetime.now(),
    )


def extract_from_document(
    path: Path | str,
    *,
    use_ocr: bool = True,
    ocr_dpi: int = DEFAULT_OCR_DPI,
    use_ocr_cache: bool = True,
) -> PdfExtractionResult:
    """
    Единая точка входа для заявок: PDF или Word (.docx).

    PDF делегирует в extract_from_pdf; Word — текст + марки + организации.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_from_pdf(
            file_path,
            use_ocr=use_ocr,
            ocr_dpi=ocr_dpi,
            use_ocr_cache=use_ocr_cache,
        )
    if suffix == ".docx":
        text = extract_text_from_docx(file_path)
        tables = extract_tables_from_docx(file_path)
        return _build_extraction_result(
            source_path=file_path,
            source_type="docx",
            text=text,
            tables=tables,
        )
    raise ValueError(f"Неподдерживаемый формат: {suffix}. Используйте PDF или .docx")