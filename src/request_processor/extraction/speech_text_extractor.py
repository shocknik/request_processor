"""
Извлечение марок / пунктов ТУ / подсказок org из свободного текста
(речь, письмо, короткая заявка без таблицы «марка + NхM»).

Детерминированные эвристики. Ассистент (fuzzy/LLM) — опционально позже, после HITL.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..models import CableMarkMatch
from ..parsing.cable_mark_parser import extract_document_from_text

# Стоп-слова: короткие токены, похожие на марку, но не марки
_SPEECH_STOP = frozenset(
    {
        "ту",
        "гост",
        "сто",
        "аэс",
        "ил",
        "ос",
        "ооо",
        "ао",
        "ип",
        "пао",
        "зао",
        "рф",
        "кв",
        "мм",
        "нд",
        "пнр",
        "пси",
        "мс",
        "мси",
        "туп",
        "кат",
        "тип",
        "вид",
        "см",
        "тпж",
        "фсб",
        "фса",
        "инн",
        "кпп",
        "бик",
        "огрн",
        "добрый",
        "день",
        "просим",
        "стоимость",
        "сроки",
        "испытания",
        "испытаний",
        "образец",
        "образца",
        "соответствие",
        "вложении",
        "количество",
        "образцов",
        "требование",
        "метод",
        "кабель",
        "кабеля",
        "провод",
        "провода",
        "марки",
        "марка",
        "заказчик",
        "производитель",
        "сертификационных",
        "периодических",
        "контрольных",
        "приемосдаточных",
    }
)

# Контекст: «марки МГЛФ», «марка: КАГЭ», «обозначение …»
_CTX_MARKI = re.compile(
    r"(?:марк[аииы]|обозначени[ея]|тип\s+кабел\w*)\s*:?\s*"
    r"([А-ЯЁA-Z][А-ЯЁа-яёA-Za-z0-9\-\(\)/]{1,90}"
    r"(?:\s+\d+\s*[хxХ×]\s*[\d.,]+(?:\s*[хxХ×]\s*[\d.,]+)*)?"
    r"(?:[а-яёa-zA-Z\-\(\),\d/]*)?)",
    re.IGNORECASE,
)

# «кабель КАГЭ», «Кабель — Энергия-ВЗ-…», «провода … марки X» уже выше;
# здесь: продукт + тире/двоеточие/пробел + обозначение
_CTX_PRODUCT = re.compile(
    r"(?:кабел[ья]|провод\w*|образц\w*|издели\w*)\s*(?:—|-|:|=)?\s*"
    r"([А-ЯЁA-Z][А-ЯЁа-яёA-Za-z0-9\-\(\)/]{2,90}"
    r"(?:\s+\d+\s*[хxХ×]\s*[\d.,]+(?:\s*[хxХ×]\s*[\d.,]+)*)?"
    r"(?:[а-яёa-zA-Z\-\(\),\d/]*)?)",
    re.IGNORECASE,
)

# Полное обозначение с пожарным классом, без обязательного «NхM»
# Энергия-ВЗ-МКВЭклВКснг(А)-FRLS-УФ
_FIRE_FULL = re.compile(
    r"\b("
    r"[А-ЯЁA-Z][А-ЯЁа-яёA-Za-z0-9\-]{2,50}"
    r"нг\s*\(\s*[АAаa]\s*\)"
    r"(?:-?(?:FRLS|FRHF|LS|HF|LSLTx|LSLT|FR|ХЛ|УФ|УХЛ|Т|ng|HF))"
    r"(?:-[А-ЯЁA-Za-zа-яё0-9]{1,12})*"
    r")\b",
    re.IGNORECASE,
)

# Пункты: «пункты 1.1.3, 1.2.1» / «п. 1.6.6» / «Требование — п. 1.6.6»
_CLAUSES_LIST = re.compile(
    r"(?:пункт[ыа]?|п{1,2}\.?)\s*"
    r"((?:\d+(?:\.\d+){1,5})"
    r"(?:\s*[,;]\s*(?:\d+(?:\.\d+){1,5}))*"
    r"(?:\s+и\s+(?:\d+(?:\.\d+){1,5}))?)",
    re.IGNORECASE,
)
_CLAUSE_LABELED = re.compile(
    r"(?:требовани[ея]|метод|методик\w*|проверк\w*)\s*[—\-:.]?\s*"
    r"(?:п\.?\s*)?(\d+(?:\.\d+){1,5})",
    re.IGNORECASE,
)

# Обрезка хвоста: «на соответствие», «по ТУ», «с поставкой»
_TRAIL_CUT = re.compile(
    r"\s+(?:на\s+соответствие|по\s+ту|по\s+гост|с\s+поставкой|во\s+вложении|"
    r"в\s+количестве|ту\s+\d|гост\s+\d|для\s+|при\s+|и\s+сроки|"
    r"пункты|пункт|п\.|метод|требовани).*$",
    re.IGNORECASE,
)


def extract_tu_clauses(text: str) -> list[str]:
    """Пункты документа: 1.6.6, 4.5.7, 1.1.3 … (уникальные, порядок появления)."""
    if not (text or "").strip():
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        for part in re.split(r"[,;]|\s+и\s+", raw):
            p = part.strip().rstrip(".")
            if not re.fullmatch(r"\d+(?:\.\d+){1,5}", p):
                continue
            # отсечь «похоже на дату» 12.07.2026
            bits = p.split(".")
            if len(bits) == 3 and all(len(b) >= 2 for b in bits):
                if int(bits[2]) > 31:  # год
                    continue
            if p not in seen:
                seen.add(p)
                found.append(p)

    for m in _CLAUSES_LIST.finditer(text):
        _add(m.group(1))
    for m in _CLAUSE_LABELED.finditer(text):
        _add(m.group(1))
    return found


def _normalize_candidate(raw: str) -> str:
    mark = (raw or "").strip(" .,;:\n\t«»\"'")
    mark = mark.replace("×", "х").replace("Х", "х")
    mark = re.sub(r"\s+", " ", mark)
    mark = _TRAIL_CUT.sub("", mark).strip(" .,;:")
    # OCR/типографика скобок
    mark = re.sub(r"нг\s*\(\s*A\s*\)", "нг(А)", mark, flags=re.IGNORECASE)
    mark = re.sub(r"нг\s*\(\s*А\s*\)", "нг(А)", mark, flags=re.IGNORECASE)
    return mark.strip()


def is_plausible_speech_mark(mark: str) -> bool:
    """Допускает бренд без сечения (КАГЭ, МГЛФ) и полные нг(А)-… без NхM."""
    if not mark or len(mark) < 3:
        return False
    if len(mark) > 120:
        return False
    if not re.match(r"^[А-ЯЁA-Z]", mark):
        return False
    low = mark.lower().replace("ё", "е")
    if low in _SPEECH_STOP:
        return False
    # одно «слово»-стоп из начала
    first = re.split(r"[\s\-/]", low, maxsplit=1)[0]
    if first in _SPEECH_STOP:
        return False
    if re.match(r"^(?:ту|гост|сто)\b", low):
        return False
    if re.search(r"\d{2}\.\d{4}", mark):  # дата
        return False
    # слишком «фразоподобно»
    if " " in mark and len(mark.split()) > 6:
        return False
    letters = re.sub(r"[^А-ЯЁа-яёA-Za-z]", "", mark)
    if len(letters) < 3:
        return False
    # чисто служебные аббревиатуры 2–3 буквы без цифр/дефисов — нет
    # (КАГЭ = 4 — ок; ОС = 2 — стоп)
    if len(letters) <= 2 and not re.search(r"[\d\-]", mark):
        return False
    return True


def _context_snippet(text: str, start: int, end: int, radius: int = 160) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[left:right].strip())


def _iter_candidates(text: str) -> Iterable[tuple[str, int, int]]:
    for pattern in (_FIRE_FULL, _CTX_MARKI, _CTX_PRODUCT):
        for m in pattern.finditer(text):
            raw = m.group(1) if m.lastindex else m.group(0)
            yield raw, m.start(1) if m.lastindex else m.start(), m.end(1) if m.lastindex else m.end()


def find_speech_marks(text: str) -> list[CableMarkMatch]:
    """
    Марки из свободного текста (письмо/речь).

    1) Фразы «марки …», «кабель …», полные нг(А)-…
    2) Словарь известных имён (справочник 300): если в тексте есть «ВВГ», «КПС» —
       считаем это маркой, даже без сечения.
    Пункты ТУ из того же текста кладутся в requirements_raw.
    """
    base = (text or "").replace("\xa0", " ")
    base = base.replace("—", "-").replace("–", "-")
    if not base.strip():
        return []

    clauses = extract_tu_clauses(base)
    clauses_joined = ", ".join(clauses) if clauses else None
    doc_global = extract_document_from_text(base)

    seen: set[str] = set()
    out: list[CableMarkMatch] = []

    def _remember(mark: str, start: int, end: int) -> None:
        nonlocal out
        mark = _normalize_candidate(mark)
        if not mark:
            return
        # словарь повышает доверие: известное имя — всегда ок; иначе speech-правила
        from .mark_lexicon import lookup_brand

        canon = lookup_brand(mark)
        if canon:
            mark = canon
        elif not is_plausible_speech_mark(mark):
            return
        key = re.sub(r"\s+", "", mark.lower().replace("ё", "е"))
        if key in seen:
            return
        if any(key in s or s in key for s in seen if abs(len(s) - len(key)) > 2):
            shorter = [s for s in list(seen) if s in key and s != key]
            if shorter:
                for s in shorter:
                    seen.discard(s)
                    out = [m for m in out if re.sub(r"\s+", "", m.mark.lower()) != s]
            else:
                if any(key in s for s in seen):
                    return
        seen.add(key)
        ctx = _context_snippet(base, start, end)
        doc = extract_document_from_text(ctx) or doc_global
        out.append(
            CableMarkMatch(
                mark=mark,
                context=ctx,
                document=doc,
                requirements_raw=clauses_joined,
            )
        )

    for raw, start, end in _iter_candidates(base):
        _remember(raw, start, end)

    # Словарь справочника: «… кабель ВВГнг …» без явного «марки»
    try:
        from .mark_lexicon import find_lexicon_marks_in_text

        for brand, start, end in find_lexicon_marks_in_text(base):
            _remember(brand, start, end)
    except Exception:  # noqa: BLE001 — словарь опционален
        pass

    return out


def merge_marks_prefer_richer(
    primary: list[CableMarkMatch],
    extra: list[CableMarkMatch],
) -> list[CableMarkMatch]:
    """Слить structural + speech: без дублей, requirements/document — с speech."""
    by_key: dict[str, CableMarkMatch] = {}
    order: list[str] = []

    def _key(m: str) -> str:
        return re.sub(r"\s+", "", m.lower()).replace("x", "х")

    for m in primary + extra:
        k = _key(m.mark)
        if k not in by_key:
            by_key[k] = m
            order.append(k)
            continue
        old = by_key[k]
        # дополнить requirements / document
        req = old.requirements_raw or m.requirements_raw
        doc = old.document or m.document
        # более длинное обозначение предпочтительнее
        mark = old.mark if len(old.mark) >= len(m.mark) else m.mark
        by_key[k] = CableMarkMatch(
            mark=mark,
            context=old.context or m.context,
            document=doc,
            requirements_raw=req,
        )
    return [by_key[k] for k in order]
