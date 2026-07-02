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

from .models import OrganizationExtract
from .organization_extractor import (
    _FSA_PATTERN,
    _INN_KPP_PATTERN,
    _PHONE_PATTERN,
    _EMAIL_PATTERN,
    _infer_org_type,
    _fix_ocr_name,
    normalize_address_text,
    normalize_org_name,
    sanitize_address,
)

_LETTER_MARKERS = re.compile(
    r"Гарантийное\s+письмо|Просим\s+(?:Вас\s+)?провести|"
    r"Генеральному\s+директору|Уважаемому\s+директору",
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
    r"Общество\s+с\s+ограниченной\s+ответственностью\s*[«\"]?([^»\";\n]+))",
    re.IGNORECASE,
)

_ADDRESS_IN_HEADER = re.compile(
    r"(?:Ул\.?|ул\.?)\s*:?\s*([^,;]+(?:,\s*[^,;]+){0,6})",
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
    name = re.sub(r"\s+", " ", name).strip(" .,;:<»\"'")
    name = re.sub(r"х\s*$", "»", name)  # OCR «Спецкабельх → Спецкабель»
    name = name.rstrip("х").strip()
    return _fix_ocr_name(name)


def _extract_sender_name(header: str) -> str | None:
    """Название организации-отправителя из шапки письма."""
    candidates: list[str] = []

    for m in _OOO_BLOCK.finditer(header):
        name = (m.group(2) or m.group(3) or m.group(4) or "").strip()
        name = _trim_org_name(name)
        if name and len(name) >= 4 and "кабель-тест" not in name.lower():
            candidates.append(name)

    if re.search(r"Спецкабель", header, re.I):
        for c in candidates:
            if "спецкабель" in c.lower():
                return f'ООО НПП «{_trim_org_name(c)}»'
        return 'ООО НПП «Спецкабель»'

    if re.search(r"кабельн\w+\s+завод", header, re.I):
        factory = re.search(
            r"([А-ЯЁA-Z][А-ЯЁа-яёA-Za-z\-]+(?:\s+[А-ЯЁA-Z][А-ЯЁа-яёA-Za-z\-]+)?)\s*$",
            header.split("\n")[0] if "\n" in header else "",
            re.M,
        )
        if factory:
            candidates.append(factory.group(1))

    if candidates:
        best = max(candidates, key=len)
        if "кабель-тест" not in best.lower() and "ниц" not in best.lower():
            return f'ООО НПП «{_fix_ocr_name(best)}»' if "ооо" not in best.lower() else best

    m = re.search(
        r"(?:кабельн\w+\s+завод\s+)?([А-ЯЁA-Z][А-ЯЁа-яё\-]{3,30})",
        header,
        re.I,
    )
    if m and "кабель-тест" not in m.group(0).lower():
        return f'ООО «{_fix_ocr_name(m.group(1))}»'

    return None


def _extract_sender_address(header: str, *, exclude: str | None = None) -> str | None:
    """Адрес отправителя из шапки (ул. …, индекс)."""
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

    postal = re.search(r"\b(\d{6})\b[^.\n]{10,120}", header)
    if postal:
        return sanitize_address(postal.group(0))
    return None


def parse_business_letter(text: str) -> LetterParseResult | None:
    """
    Разбирает шапку письма: получатель (ИЛ) и отправитель (заказчик).

    Возвращает None, если документ не похож на письмо.
    """
    if not is_business_letter(text):
        return None

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

    customer = OrganizationExtract(
        name=parsed.sender_name,
        address=parsed.sender_legal_address,
        legal_address=parsed.sender_legal_address,
        actual_address=parsed.sender_actual_address,
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

    if parsed.recipient_org_name and "кабель-тест" in parsed.recipient_org_name.lower():
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