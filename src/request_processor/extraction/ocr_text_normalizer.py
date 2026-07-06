"""
Постобработка сырого OCR-текста заявок.

Tesseract часто выдаёт русский текст латиницей: «Poccumickaa Peaepauna», «Mocksa».
Нормализация применяется к полю ``text`` в JSON и к поиску org/марок.
"""

from __future__ import annotations

import re

from ..parsing.cable_mark_parser import fix_ocr_document_text
from .ocr_mark_normalizer import _LATIN_TO_CYR

# Не трогаем email, URL, LAN-обозначения, англ. подписи
_PROTECTED_SPAN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|"
    r"https?://\S+|"
    r"\b(?:Cat\s*5\w|UTP|SF/?UTP|F/?UTP|Prepared\s+by|Phone:|/Phone:|ext\.)\b",
    re.IGNORECASE,
)


def _apply_regex_fixes(text: str, pairs: tuple[tuple[str, str], ...]) -> str:
    for pattern, repl in pairs:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


_ADDRESS_FIXES: tuple[tuple[str, str], ...] = (
    (r"Poccumickaa\s+Peaepauna,?\s*", "Российская Федерация, "),
    (r"KaAyKCKaA\s+OOACCTE", "Калужская область"),
    (r"A3@PXXUHCKMM\s+PANOH", "Дзержинский район"),
    (r"A\.\s*Kuaetoso", "д. Жилетово"),
    (r"\bKuaetoso\b", "Жилетово"),
    (r"YA\.\s*MpOMbiLuAeHHas", "ул. Промышленная"),
    (r"\bYA\.\s*", "ул. "),
    (r"\bA\.\s*(\d+)\b", r"д. \1"),
    (r"\bCTP\.\s*(\d+)\b", r"стр. \1"),
)

_SPECLAN_FIXES: tuple[tuple[str, str], ...] = (
    (r"\b(?:CMELVIAH|CMELAN|SPECLAN|Cneu\w*lan|Sneu\w*lan)\b", "СПЕЦЛАН"),
    (r"\bMapkax?\s+Kabena?\b", "Марках кабеля"),
    (r"\bKonuyectBe\b", "В количестве"),
    (r"ZH\s+(?:ur|Hr|hr|ng|нr|Нг)\s*\(\s*A\s*\)", "ZH нг(А)"),
    (r"TapaHTuiHoe\s+nucbmMo", "Гарантийное письмо"),
    (r"Mpocum\s+Bac\s+nprovect\w*", "Просим Вас провести"),
    (r"TeHepanbHomy\s+AnpekTopy", "Генеральному директору"),
    (r"TeHepanbHbIl\s+AUpeKTOp", "Генеральный директор"),
    (r"\bOOO\s+HNN\b", "ООО НПП"),
    (r"Cneu\w*abel\w*", "Спецкабель"),
    (r"Cneukabenl?", "Спецкабель"),
    (r"Kabenb-TecT", "Кабель-Тест"),
    (r"\bYa\.\s+", "ул. "),
    (r"\bBuptocuuka\b", "Бутырская"),
    (r"\bMocksa\b", "Москва"),
    (r"\bKopn\.\s*", "Корп. "),
    (r"\bnom\.\s*", "пом. "),
    (r"\bkom\.\s*", "ком. "),
    (r"\bTen\.:", "Тел.:"),
    (r"\bCait:", "Сайт:"),
    (r"\bOFPH\b", "ОГРН"),
    (r"\bVYHH/KNN\b", "ИНН/КПП"),
    (r"\bOKNO\b", "ОКПО"),
    (r"\bUcnonuntenb\b", "Исполнитель"),
    (r"\bNocnegyrouj\w*\s+onsaty\b", "Последующую оплату"),
    (r"\brapaHTupyem\b", "гарантируем"),
    (r"\bUCnbITAH\w*\b", "испытания"),
    (r"\bnpvemo-cAaTo\w*\b", "приемо-сдаточные"),
)

_PERIODIC_FIXES: tuple[tuple[str, str], ...] = (
    (r"N?Mpocum\s+Bac\s+nprovectm?", "Просим Вас провести"),
    (r"TeEHEPAAbHOMY\s+ANPeKTOPy", "Генеральному директору"),
    (r"KaayxKckni\s+KaGeAbHbIN\s+3GB0A", "Калужский кабельный завод"),
    (r"Nnepuoauyeckie\s+UCNblITAHMA", "периодические испытания"),
    (r"\bBBI-MHr\(A\)", "ВВГнг(А)"),
    (r"\bBBI-", "ВВГ-"),
    (r"NBCur\(A\)-LS", "ПВСнг(А)-LS"),
    (r"\bAllyB\b", "АПуВ"),
    (r"\bNBIBB\b", "ПБГВВ"),
    (r"3x40K", "3х4ок"),
    (r"Nposoa\s+Mapkn\w*", "Провод марки"),
    (r"Ka6eAb\s+CHACBON\s+MAPK:", "Кабель силовой марки:"),
)

_MISC_FIXES: tuple[tuple[str, str], ...] = (
    (r"(?<=[А-ЯЁA-Zа-яё])l(?=[хx×]|\d)", "1"),
    (r"(?<=[А-ЯЁA-Zа-яё])I(?=[хx×]|\d)", "1"),
    (r"\bl(?=[хx×]\s*[\d.,])", "1"),
    (r"\bI(?=[хx×]\s*[\d.,])", "1"),
    (r"\bЗ\s*х\b", "3х"),
    (r"(\d+)\s*х\s*ок\b", r"\1х4ок"),
    (r"N;\s*PE", "(N,PE)"),
    (r"\)J\b", ")"),
    (r"PEJ", "PE)"),
    (r"С\s+анкт", "Санкт"),
    (r"Р\s+ОССИЯ", "РОССИЯ"),
)


def _latin_ratio(segment: str) -> float:
    letters = [c for c in segment if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if "a" <= c <= "z" or "A" <= c <= "Z")
    return latin / len(letters)


def _homoglyph_line(line: str) -> str:
    """Латиница→кириллица в строке, если похоже на русский OCR (без email/URL)."""
    if _latin_ratio(line) < 0.55:
        return line
    if "@" in line or "http" in line.lower():
        return line

    parts: list[str] = []
    last = 0
    for match in _PROTECTED_SPAN.finditer(line):
        if match.start() > last:
            chunk = line[last : match.start()]
            parts.append(chunk.translate(_LATIN_TO_CYR) if _latin_ratio(chunk) >= 0.55 else chunk)
        parts.append(match.group(0))
        last = match.end()
    tail = line[last:]
    if tail:
        parts.append(tail.translate(_LATIN_TO_CYR) if _latin_ratio(tail) >= 0.55 else tail)
    return "".join(parts)


def normalize_ocr_text(text: str) -> str:
    """
    Исправляет типичный «латинский» OCR русского текста.

    Вызывается после Tesseract/EasyOCR, до сохранения в JSON и кэш.
    """
    if not text or not text.strip():
        return text

    text = fix_ocr_document_text(text)
    for fixes in (_ADDRESS_FIXES, _SPECLAN_FIXES, _PERIODIC_FIXES, _MISC_FIXES):
        text = _apply_regex_fixes(text, fixes)

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if (
            stripped
            and _latin_ratio(stripped) >= 0.45
            and "@" not in stripped
            and "http" not in stripped.lower()
        ):
            line = _homoglyph_line(line)
        lines.append(line)
    text = "\n".join(lines)
    return re.sub(r"  +", " ", text)