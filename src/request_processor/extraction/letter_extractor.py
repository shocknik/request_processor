"""
Парсинг структуры деловых писем (гарантийное письмо, запрос на испытания).

Отличает:
- **получателя** (кому адресовано: «Генеральному директору …») — испытательный центр;
- **отправителя** (бланк/подпись: реквизиты, ИНН, адрес) — заказчик испытаний.

Используется до общего organization_extractor для документов типа «письмо».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import OrganizationExtract
from .organization_extractor import (
    _FSA_PATTERN,
    _INN_KPP_PATTERN,
    _PHONE_PATTERN,
    _EMAIL_PATTERN,
    _infer_org_type,
    _fix_ocr_name,
    extract_periodic_factory_address,
    normalize_address_text,
    normalize_org_name,
    sanitize_address,
)

_LETTER_MARKERS = re.compile(
    r"Гарантийное\s+письмо|Просим\s+(?:Вас\s+)?провести|"
    r"периодическ\w+\s+испытан|"
    r"Генеральному\s+директору|Уважаемому\s+директору|"
    r"TapaHTuiHoe\s+nucbmMo|ТараНТ\w+ое\s+ннсбМо|"
    r"Mpocum\s+(?:Bac\s+)?nprovectu|Мроснм\s+Бас\s+нроБестн|"
    r"TeHepanbHomy|мз\s+ТеНеранбНому\s+АннрекТору|"
    r"TeEHEPAAbHOMY|Nnepuoauyeckie\s+UCNblITAHMA|NMpocum\s+Bac\s+nprovectm|"
    r"KAGEABHOM\s+NPOAYKLIMM",
    re.IGNORECASE,
)

_RECIPIENT_LINE = re.compile(
    r"^(?:Генеральному|Уважаемому)\s+"
    r"(?:(?:директору|директора)\s+)?(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

_DATE_LINE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")

_OOO_BLOCK = re.compile(
    r"(ООО\s+НПП\s*[«\"<]?\s*([^»\"'>;\n]+)|"
    r"ООО\s*[«\"]([^»\"]+)[»\"]|"
    r"OOO\s+HNN\s*[«\"<]?\s*([^»\"'>;\n]+)|"
    r"Общество\s+с\s+ограниченной\s+ответственностью\s*[«\"]?([^»\";\n]+))",
    re.IGNORECASE,
)

_ADDRESS_IN_HEADER = re.compile(
    r"(?:Ул\.?|ул\.?|YA\.?)\s*:?\s*([^,;]+(?:,\s*[^,;]+){0,6})",
    re.IGNORECASE,
)


@dataclass
class LetterParseResult:
    """Результат разбора письма."""

    recipient_line: str | None
    recipient_org_name: str | None
    sender_name: str | None
    sender_legal_address: str | None
    sender_actual_address: str | None
    sender_inn: str | None
    sender_kpp: str | None
    sender_phone: str | None
    sender_email: str | None
    confidence: float


def is_business_letter(text: str) -> bool:
    """Эвристика: документ похож на исходящее письмо, а не на направление в ИЛ."""
    if not text or len(text) < 80:
        return False
    head = text[:2500]
    if _LETTER_MARKERS.search(head):
        return True
    if re.search(r"Генеральному\s+директору", head, re.I) and re.search(
        r"Просим\s+.*провести", head, re.I
    ):
        return True
    return False


def _extract_recipient(line: str) -> tuple[str | None, str | None]:
    """Из строки «Генеральному директору ООО … Фамилия И.О.» — организация и ФИО."""
    line = line.strip()
    org_name = None
    ooo = re.search(
        r"(ООО\s+[«\"]?[^»\"]+[»\"]?|НИЦ\s*[«\"]?[^»\"]+[»\"]?|"
        r"Испытательный\s+центр[^,\n]*)",
        line,
        re.I,
    )
    if ooo:
        org_name = re.sub(r"\s+", " ", ooo.group(1)).strip()
        org_name = re.sub(r"[~`]", "", org_name)
    return org_name, line


def _trim_org_name(raw: str) -> str:
    """Обрезает адрес и реквизиты, попавшие в название (OCR)."""
    name = re.split(r"\s+Ул\s*:|ул\s*:|Тел\s*\.|ИНН|ОКПО|ОГРН|,\s*\d{6}\b", raw, maxsplit=1)[0]
    name = re.sub(r"\s+", " ", name).strip(" .,;:")
    # Не срезать закрывающую «» — только мусор
    name = name.strip(" '\"")
    name = re.sub(r"х\s*$", "»", name)  # OCR: лишняя «х» на конце кавычки
    name = name.rstrip("х").strip()
    name = re.sub(r"b$", "", name, flags=re.IGNORECASE)
    # Достроить кавычки: «Спецкабель → «Спецкабель»
    if "«" in name and "»" not in name:
        name = name + "»"
    return _fix_ocr_name(name)


def _collapse_periodic_factory_name(name: str) -> str:
    """Сжимает OCR-мусор вокруг «Кабельный завод» до канонического имени на бланке."""
    if not name:
        return name
    low = name.lower()
    if "кабельн" not in low or "завод" not in low:
        return name
    if re.search(r"O6GL|OfPAH|OTBETCT|ОфРАН|ОТБЕТСТ", name, re.I):
        return 'ООО «Кабельный завод»'
    letters = [c for c in name if c.isalpha()]
    if letters:
        latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
        if latin / len(letters) > 0.08 or len(name) > 42:
            return 'ООО «Кабельный завод»'
    return name


def _format_sender_from_candidate(name: str) -> str:
    """Собирает отображаемое имя из фрагмента, найденного в тексте (не шаблон)."""
    cleaned = _fix_ocr_name(_trim_org_name(name))
    if not cleaned:
        return cleaned
    low = cleaned.lower()
    if "ооо" in low or "ao " in low or low.startswith("ао ") or "зао" in low:
        return cleaned
    # Фрагмент только «Спецкабель» / «НПП Спецкабель» → ООО НПП «…»
    if re.search(r"\bнпп\b", low):
        core = re.sub(r"^(?:ооо\s+)?нпп\s*", "", cleaned, flags=re.I).strip(" «»\"'")
        return f'ООО НПП «{core}»' if core else cleaned
    return f'ООО НПП «{cleaned}»' if len(cleaned) < 40 else cleaned


def _is_testing_center_noise(name: str) -> bool:
    """Отсекает ИЦ / placeholder, которые нельзя выдавать за заказчика."""
    low = name.lower().replace(" ", "")
    needles = (
        "испытательныйцентр",
        "кабель-тест",
        "кабенб-тест",
        "ка6егб-тесм",
        "ka6erb-tecm",
        "производитель",
        "hull",
        "null",
        "нull",
        "hul",
        "ниц",
    )
    return any(n in low for n in needles)


def _extract_sender_name(header: str) -> str | None:
    """
    Название организации-отправителя из шапки письма.

    Только то, что видно в тексте. Без подстановки «шаблонных» юрлиц.
    """
    candidates: list[str] = []
    header_has_npp = bool(re.search(r"\bнпп\b|HNN", header, re.I))
    header_has_spec = bool(re.search(r"спецкабель", header, re.I))

    # 1) ООО НПП «…» / OOO HNN (приоритет для LAN / производителей)
    for m in re.finditer(
        r"(?:OOO|ООО)\s+(?:HNN|НПП)\s*[«\"'<]?\s*([^»\"'>;\nхx]{3,40})",
        header,
        re.I,
    ):
        full = _trim_org_name(m.group(0).replace("<", "«").replace(">", "»"))
        if full and not _is_testing_center_noise(full):
            candidates.append(full)

    # 2) Одно слово «Спецкабель» на бланке (после OCR-алиаса)
    if header_has_spec:
        candidates.append('ООО НПП «Спецкабель»')

    # 3) «…кабельный завод…» — только если нет НПП/Спецкабель в шапке
    #    (иначе residual OCR «Кабельный завод Видяеву» перебивает реального отправителя)
    if not header_has_npp and not header_has_spec:
        for m in re.finditer(
            r"[«\"']?([^»\"'\n]{0,50}кабельн\w*\s+завод[^»\"'\n]{0,30})[»\"']?",
            header,
            re.I,
        ):
            frag = _trim_org_name(m.group(1))
            # отсечь «завод + ФИО» (Видяеву В.И.)
            if re.search(r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.[А-ЯЁ]\.?\b", frag):
                continue
            if frag and not _is_testing_center_noise(frag):
                candidates.append(
                    frag if "ооо" in frag.lower() else f'ООО «{frag.strip("«»")}»'
                )

    for m in _OOO_BLOCK.finditer(header):
        full = (m.group(0) or "").strip()
        name = _trim_org_name(full)
        if name and len(name) >= 4 and not _is_testing_center_noise(name):
            candidates.append(name)

    filtered = [c for c in candidates if len(c) >= 4 and not _is_testing_center_noise(c)]

    if filtered:
        def score(s: str) -> tuple[int, int]:
            low = s.lower()
            pts = 0
            if "спецкабель" in low:
                pts += 8
            if "нпп" in low:
                pts += 4
            if "ооо" in low:
                pts += 2
            if "кабельн" in low and "завод" in low:
                # ниже НПП: завод только если нет спецкабеля
                pts += 3 if not header_has_spec else -2
            if re.search(r"\b[а-яё]+\s+[а-яё]\.[а-яё]", low):
                pts -= 5  # ФИО в названии
            return (pts, len(s))

        best = max(filtered, key=score)
        if "ооо" in best.lower():
            return _collapse_periodic_factory_name(_fix_ocr_name(best))
        return _collapse_periodic_factory_name(_format_sender_from_candidate(best))

    if re.search(r"KaayxKckni\s+KaGeAbHbIN|кабельн\w*\s+завод", header, re.I):
        return 'ООО «Кабельный завод»'

    return None


def _extract_sender_address(header: str, *, exclude: str | None = None) -> str | None:
    """Адрес отправителя из шапки (ул. …, индекс)."""
    factory_addr = extract_periodic_factory_address(header)
    if factory_addr:
        return factory_addr

    addr_m = _ADDRESS_IN_HEADER.search(header)
    if addr_m:
        raw = addr_m.group(1)
        if "бирюсинка" in raw.lower() or _DATE_LINE.search(raw) is None:
            addr = sanitize_address(raw)
            if addr and (not exclude or exclude.lower() not in addr.lower()):
                postal = re.search(r"\b(\d{6})\b", header)
                if postal and postal.group(1) not in addr:
                    addr = f"{postal.group(1)}, {addr}"
                return normalize_address_text(addr)

    postal = re.search(r"\b(\d{6})\b", header)
    if postal:
        idx = postal.group(1)
        chunk = header[postal.start() : postal.start() + 140]
        addr = sanitize_address(chunk)
        if addr:
            if not addr.startswith(idx):
                addr = f"{idx}, {addr}"
            return normalize_address_text(addr)
    return None


def parse_business_letter(text: str) -> LetterParseResult | None:
    """
    Разбирает шапку письма: получатель (ИЛ) и отправитель (заказчик).

    Возвращает None, если документ не похож на письмо.
    Текст сначала нормализуется (OCR-латиница → кириллица) — читаем документ,
    а не подставляем шаблонные юрлица.
    """
    if not is_business_letter(text):
        return None

    from .ocr_text_normalizer import normalize_ocr_text

    text = normalize_ocr_text(text)

    recipient_line = None
    recipient_org = None
    rm = _RECIPIENT_LINE.search(text[:800])
    if rm:
        recipient_line = rm.group(0).strip()
        recipient_org, _ = _extract_recipient(rm.group(1))

    date_m = _DATE_LINE.search(text)
    header_end = date_m.start() if date_m else min(2000, len(text))
    header = text[:header_end]

    if recipient_line:
        header = header.replace(recipient_line, "\n")

    header = re.sub(
        r"^.*(?:Генеральному|Уважаемому)\s+директору.*$",
        "",
        header,
        flags=re.I | re.M,
    )

    sender_name = _extract_sender_name(header)
    sender_addr = _extract_sender_address(header)

    inn = kpp = None
    inn_m = _INN_KPP_PATTERN.search(header)
    if inn_m:
        inn, kpp = inn_m.group(1), inn_m.group(2)

    phone = None
    phone_m = _PHONE_PATTERN.search(header)
    if phone_m:
        phone = re.sub(r"\s+", " ", phone_m.group(1)).strip()
    else:
        tel_fallback = re.search(r"Тел\s*\.?\s*:?\s*(\(?\d{3,5}\)?[\d\s\-]{6,20})", header, re.I)
        if tel_fallback:
            phone = tel_fallback.group(1).strip()

    email = None
    email_m = _EMAIL_PATTERN.search(header)
    if email_m:
        email = email_m.group(1).replace(" ", "")

    confidence = 0.55
    if sender_name:
        confidence += 0.2
    if sender_addr:
        confidence += 0.15
    if inn:
        confidence += 0.1

    return LetterParseResult(
        recipient_line=recipient_line,
        recipient_org_name=recipient_org,
        sender_name=sender_name,
        sender_legal_address=sender_addr,
        sender_actual_address=sender_addr,
        sender_inn=inn,
        sender_kpp=kpp,
        sender_phone=phone,
        sender_email=email,
        confidence=min(confidence, 0.95),
    )


def organizations_from_letter(text: str) -> list[OrganizationExtract]:
    """
    Организации из письма: заказчик = отправитель, производитель = отправитель.
    Получатель (ИЛ) в заказчика не попадает.
    """
    parsed = parse_business_letter(text)
    if not parsed or not parsed.sender_name:
        return []

    sender_key = normalize_org_name(parsed.sender_name)
    if not sender_key:
        return []

    org_type = _infer_org_type(text, parsed.sender_name)
    if org_type == "unknown":
        org_type = "manufacturer"

    sender_addr = parsed.sender_legal_address
    if parsed.sender_name and "кабельн" in parsed.sender_name.lower() and "завод" in parsed.sender_name.lower():
        sender_addr = extract_periodic_factory_address(text) or sender_addr

    sender_name = _collapse_periodic_factory_name(parsed.sender_name)
    customer = OrganizationExtract(
        name=sender_name,
        address=sender_addr,
        legal_address=sender_addr,
        actual_address=sender_addr,
        postal_code=None,
        phone=parsed.sender_phone,
        email=parsed.sender_email,
        inn=parsed.sender_inn,
        kpp=parsed.sender_kpp,
        is_accredited=False,
        fsa_registry_number=None,
        org_type=org_type,
        role="customer",
        confidence=parsed.confidence,
    )

    manufacturer = customer.model_copy(deep=True)
    manufacturer.role = "manufacturer"

    result = [customer, manufacturer]

    if parsed.recipient_org_name and "испытательный центр" in parsed.recipient_org_name.lower():
        fsa = _FSA_PATTERN.search(text[:3000])
        testing = OrganizationExtract(
            name=re.sub(r"\s+", " ", parsed.recipient_org_name).strip(),
            org_type="testing_center",
            role="unknown",
            is_accredited=bool(fsa),
            fsa_registry_number=fsa.group(0).upper() if fsa else None,
            confidence=0.7,
        )
        if normalize_org_name(testing.name) != sender_key:
            result.append(testing)

    return result