"""
Постобработка OCR для марок кабелей.

Tesseract часто распознаёт кириллицу латиницей (KCBur → КСБнг).
В марках кабелей бренд и пожарный класс — преимущественно кириллица;
латиница сохраняется в LAN (СПЕЦЛАН, Cat 5e, UTP).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Латиница → кириллица (типичные OCR-подмены в обозначениях марок)
_LATIN_TO_CYR = str.maketrans(
    {
        "A": "А",
        "B": "Б",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "Р",
        "T": "Т",
        "X": "Х",
        "Y": "У",
        "a": "а",
        "b": "б",
        "c": "с",
        "e": "е",
        "h": "н",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "р",
        "t": "т",
        "x": "х",
        "y": "у",
        "u": "н",
        "r": "г",
        "g": "г",
        "l": "л",
        "i": "и",
        "n": "н",
        "v": "в",
        "w": "ш",
        "z": "з",
        "d": "д",
        "f": "ф",
        "s": "с",
        "j": "й",
    }
)

_LAN_MARK_PATTERN = re.compile(
    r"СПЕЦЛАН|(?:^|\s)(?:F/?|SF/?)UTP|(?:^|\s)(?:S/?FTP)|Cat\s*\d|U/?UTP",
    re.IGNORECASE,
)

# Кириллические омоглифы → латиница в LAN-фрагментах (UТР→UTP, РVС→PVC)
_CYR_TO_LAT_LAN = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "у": "y",
        "х": "x",
        "т": "t",
        "к": "k",
        "м": "m",
        "н": "h",
        "в": "b",
    }
)

# OCR пожарных суффиксов: ЕВНЕ→FRHF (Спецкабель PDF №1527 и аналоги)
_FIRE_OCR_FIXES: tuple[tuple[str, str], ...] = (
    (r"ЕВНЕ", "FRHF"),
    (r"ЕВН[ЕE]", "FRHF"),
    (r"FRНЕ", "FRHF"),
    (r"FRНF", "FRHF"),
    (r"FRН[ЕE]", "FRHF"),
    (r"ЕВLS", "FRLS"),
    (r"ЕВL[SС]", "FRLS"),
    (r"FRL[SС]", "FRLS"),
    (r"нг\s*\(\s*[АAаa]\s*\)\s*-\s*ЕВНЕ", "нг(А)-FRHF"),
    (r"нг\s*\(\s*[АAаa]\s*\)\s*-\s*ЕВLS", "нг(А)-FRLS"),
    (r"НГ\s*\(\s*[АAаa]\s*\)", "нг(А)"),
    (r"Нг\s*\(\s*[АAаa]\s*\)", "нг(А)"),
)
_SIZE_START = re.compile(
    r"\d+\s*[зЗпП]?\s*[хx×]",
    re.IGNORECASE,
)


def _is_lan_mark(mark: str) -> bool:
    return bool(_LAN_MARK_PATTERN.search(mark))


def _split_brand_and_tail(mark: str) -> tuple[str, str]:
    """Отделяет условное обозначение (бренд+класс) от размера «NхM»."""
    m = _SIZE_START.search(mark)
    if not m:
        return mark, ""
    return mark[: m.start()].rstrip(), mark[m.start() :]


def _fix_fire_class_letters(text: str) -> str:
    text = re.sub(r"\(\s*A\s*\)", "(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*A\s*,\s*LS\s*\)", "(А)-LS", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=[ВПА-ЯЁ])MHr\s*\(\s*A\s*\)", "нг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=[ВПА-ЯЁ])МНг\s*\(\s*A\s*\)", "нг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"нг\s*\(\s*A\s*\)", "нг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"Внг\s*\(\s*A\s*\)", "Внг(А)", text, flags=re.IGNORECASE)
    text = re.sub(r"Пнг\s*\(\s*A\s*\)", "Пнг(А)", text, flags=re.IGNORECASE)
    for pattern, repl in _FIRE_OCR_FIXES:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def normalize_lan_homoglyphs(text: str) -> str:
    """Кириллица→латиница в LAN-токенах: SF/UТР → SF/UTP, РVС → PVC, Cat 6А → Cat 6A."""
    if not text:
        return text
    # Частые склейки OCR
    repls = (
        (r"U\s*/\s*U[ТT][РP]", "U/UTP"),
        (r"F\s*/\s*U[ТT][РP]", "F/UTP"),
        (r"SF\s*/\s*U[ТT][РP]", "SF/UTP"),
        (r"S\s*/\s*F[ТT][РP]", "S/FTP"),
        (r"SF\s*/\s*T[РP]", "SF/TP"),
        (r"\bР\s*V\s*[СC]\b", "PVC"),
        (r"\bP\s*V\s*С\b", "PVC"),
        (r"\bРVС\b", "PVC"),
        (r"\bРВС\b", "PVC"),
        # OCR/homoglyph: «Сат 6» ← Cat после latin→cyr
        (r"\b[СC]ат\s*(\d\w?)\b", r"Cat \1"),
        (r"\bCat\s*(\d)[АA]\b", r"Cat \1A"),
        (r"\bcat\s*(\d)[еe]\b", r"cat \1e"),
    )
    out = text
    for pattern, repl in repls:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)
    # Омоглифы внутри shield/sheath токенов
    def _lat_token(m: re.Match[str]) -> str:
        return m.group(0).translate(_CYR_TO_LAT_LAN)

    out = re.sub(
        r"\b(?:[USF]/?/?[UТTРP]{2,4}|[SС]/?[FТTРP]{2,3}|PVC|PE|ZH|LSZH)\b",
        _lat_token,
        out,
        flags=re.IGNORECASE,
    )
    return out


# Типовые бренды: OCR-искажения → эталон (насмотренность по cable_marks / письмам)
_KNOWN_BRAND_PREFIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?:BBI|ББ[IІ1])", re.IGNORECASE), "ВВГ"),
    (re.compile(r"^(?:NBCur|NBC|NБ[СC])", re.IGNORECASE), "ПВС"),
    (re.compile(r"^(?:AllyB|АллуБ|АПуВ|АПуB)", re.IGNORECASE), "АПуВ"),
    (re.compile(r"^(?:NBIBB|NБ[IІ1]ББ|NБИББ)", re.IGNORECASE), "ПБГВВ"),
)


def _snap_known_brand_prefix(brand: str) -> str:
    """Подставляет известный бренд, если OCR дал латиницу или смесь."""
    stripped = brand.strip()
    for pattern, canonical in _KNOWN_BRAND_PREFIXES:
        if pattern.match(stripped):
            rest = pattern.sub("", stripped, count=1)
            rest = re.sub(r"^[\-–]+", "", rest)
            rest = re.sub(r"^MHr\(A\)", "нг(А)", rest, flags=re.IGNORECASE)
            rest = re.sub(r"^МНг\(A\)", "нг(А)", rest, flags=re.IGNORECASE)
            rest = re.sub(r"^\(A\)-LS", "нг(А)-LS", rest, flags=re.IGNORECASE)
            rest = re.sub(r"^ur\(A\)-LS", "нг(А)-LS", rest, flags=re.IGNORECASE)
            rest = re.sub(r"^нг\(A\)", "нг(А)", rest, flags=re.IGNORECASE)
            if rest.startswith("-"):
                return canonical + rest
            if rest.startswith("нг"):
                return canonical + rest
            if rest:
                return canonical + rest
            return canonical
    return brand


def _strip_size_price_glue(mark: str) -> str:
    """Отделяет сечение от цены без пробела: 3x2,5064500 → 3x2,50; 2x1,522500 → 2x1,5."""
    two_dec = re.search(
        rf"(\d+[хx×]\d+,)(50|25|00|75)(\d{{3,}}.*)$",
        mark,
        flags=re.IGNORECASE,
    )
    if two_dec:
        return mark[: two_dec.start()] + two_dec.group(1) + two_dec.group(2)
    one_dec = re.search(
        rf"(\d+[хx×]\d+,\d)(\d{{4,}}.*)$",
        mark,
        flags=re.IGNORECASE,
    )
    if one_dec:
        return mark[: one_dec.start()] + one_dec.group(1)
    return mark


def _strip_table_price_glue(mark: str) -> str:
    """Убирает цены таблицы, склеенные OCR с маркой (3х2,5064500,00400)."""
    mark = re.sub(r"^([1-4])\s+", "", mark)
    mark = re.sub(r"^13([xх]4ок)", r"3\1", mark, flags=re.IGNORECASE)
    mark = _strip_size_price_glue(mark)
    mark = re.sub(
        r"(-0,66)\s+.*$",
        r"\1",
        mark,
        flags=re.IGNORECASE,
    )
    mark = re.sub(
        r"\s+(?:\d{1,3}(?:\s\d{3})*,\d{2}|\d{4,},\d{2})"
        r"(?:\s+(?:\d{1,3}(?:\s\d{3})*,\d{2}|\d{4,},\d{2}))*\s*\d{0,3}$",
        "",
        mark,
    )
    mark = re.sub(
        r"(\d,\d{2})(?:\d{3,},\d{2})+.*$",
        r"\1",
        mark,
    )
    return mark.strip()


def _infer_vvg_for_size_only(mark: str) -> str:
    low = re.sub(r"\s+", "", mark.lower())
    if re.match(r"^3х4ок\(n", low) or re.match(r"^3х4ок\s*\(n", mark, re.I):
        return f"ВВГнг(А) {mark.strip()}"
    return mark


def _fix_size_ocr_tail(tail: str) -> str:
    """Правит OCR в части сечения (3x40K → 3х4ок)."""
    if not tail:
        return tail
    fixed = tail
    fixed = re.sub(r"3x40K", "3х4ок", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"3x4ok", "3х4ок", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"(\d)\s*x\s*(\d)", r"\1х\2", fixed, flags=re.IGNORECASE)
    return fixed


def _ensure_space_before_size(mark: str) -> str:
    """Вставляет пробел перед «NхM», если OCR склеил (ПВСнг(А)-LS3х2,50)."""
    mark = re.sub(
        r"((?:\([АA]\)|-LS|-HF|-LSLTx))(\d+\s*[хx])",
        r"\1 \2",
        mark,
        flags=re.IGNORECASE,
    )
    mark = re.sub(
        r"^([А-ЯЁ][А-ЯЁа-яё\-]{1,14})(\d+\s*[хx])",
        r"\1 \2",
        mark,
    )
    return mark


def _cyrillic_latin_ratio(text: str) -> tuple[int, int]:
    cyr = sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")
    lat = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return cyr, lat


# Фрагменты, где латиница в марке — норма (не трогаем при смешанном тексте)
_KEEP_LATIN_FRAGMENTS = re.compile(
    r"FRLS|FRHF|LSL|UTP|HF|LS(?:LT)?|ZH|Cat\s*5|SF/?UTP|МК|ККЗ",
    re.IGNORECASE,
)


def _fix_mixed_script_brand(brand: str) -> str:
    """Правит OCR в марке, где уже есть кириллица (не ломая FRLS/HF/UTP)."""
    result = brand
    for m in _KEEP_LATIN_FRAGMENTS.finditer(brand):
        pass  # сохраняем латинские фрагменты как есть
    # Точечные замены вне «сохранённых» зон: латинская H между кириллицей → Н
    result = re.sub(r"(?<=[А-ЯЁа-яё])H(?=[А-ЯЁа-яё])", "Н", result)
    result = re.sub(r"(?<=[А-ЯЁа-яё])F(?=[А-ЯЁа-яё])", "Ф", result)
    return _fix_fire_class_letters(result)


def latin_to_cyrillic_in_brand(brand: str) -> str:
    """Переводит латинские гомоглифы в кириллицу в части марки до размера."""
    if not brand:
        return brand
    cyr, lat = _cyrillic_latin_ratio(brand)
    if cyr >= 2 and cyr >= lat:
        return _fix_mixed_script_brand(brand)
    converted = brand.translate(_LATIN_TO_CYR)
    return _fix_fire_class_letters(converted)


def normalize_mark_after_ocr(
    mark: str,
    *,
    known_brands: set[str] | None = None,
) -> str:
    """
    Нормализует марку после OCR: латиница → кириллица в бренде, опционально — по справочнику.
    """
    if not mark or not mark.strip():
        return mark

    raw = _strip_table_price_glue(mark.strip())
    raw = normalize_lan_homoglyphs(raw)
    raw = _infer_vvg_for_size_only(raw)
    if _is_lan_mark(raw):
        return _fix_fire_class_letters(normalize_lan_homoglyphs(raw))

    brand, tail = _split_brand_and_tail(raw)
    fixed_brand = _snap_known_brand_prefix(brand)
    if fixed_brand == brand:
        fixed_brand = latin_to_cyrillic_in_brand(brand)
    else:
        fixed_brand = _fix_mixed_script_brand(fixed_brand)
    tail = _fix_size_ocr_tail(tail)
    result = _ensure_space_before_size((fixed_brand + tail).strip())
    result = _fix_fire_class_letters(result)
    result = re.sub(r"\s+\(", "(", result)
    result = re.sub(r"\(\s*N\s*,\s*PE\s*\)", "(N,PE)", result, flags=re.IGNORECASE)

    if known_brands:
        snapped = _snap_brand_prefix(result, known_brands)
        if snapped:
            result = snapped

    return result


def _snap_brand_prefix(mark: str, known_brands: set[str]) -> str | None:
    """Подставляет бренд из БД, если префикс похож после OCR-правок."""
    brand_part, tail = _split_brand_and_tail(mark)
    if not brand_part or len(brand_part) < 3:
        return None

    prefix = re.split(r"[\-–(]", brand_part, maxsplit=1)[0].strip()
    if len(prefix) < 2:
        return None

    best: tuple[float, str] | None = None
    prefix_low = prefix.lower()
    for known in known_brands:
        if not known or len(known) < 2:
            continue
        kn_low = known.lower()
        if prefix_low == kn_low or prefix_low.startswith(kn_low) or kn_low.startswith(prefix_low):
            ratio = 1.0
        else:
            ratio = SequenceMatcher(None, prefix_low, kn_low).ratio()
        if ratio >= 0.82 and (best is None or ratio > best[0]):
            best = (ratio, known)

    if best is None:
        return None

    _, matched = best
    if brand_part.lower().startswith(matched.lower()):
        return mark
    rest = brand_part[len(prefix) :]
    return matched + rest + tail


def load_known_brands_from_db(db_path) -> set[str]:
    """Загружает уникальные бренды из cable_marks для подсказки OCR."""
    from request_processor.persistence.sqlite_repo import list_cable_marks

    brands: set[str] = set()
    for row in list_cable_marks(limit=500, db_path=db_path):
        brand = (row.get("brand") or "").strip()
        if brand and len(brand) >= 2:
            brands.add(brand)
    return brands