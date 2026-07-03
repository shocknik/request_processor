"""
Извлечение сведений об организациях из текста заявок и писем (PDF/OCR/Word).
"""

from __future__ import annotations

import re
from typing import Literal

from ..models import OrganizationExtract, OrganizationRole

OrgType = Literal[
    "manufacturer",
    "certification_body",
    "testing_center",
    "dealer",
    "unknown",
]

_ROLE_LABELS: dict[str, OrganizationRole] = {
    "заказчик": "customer",
    "покупатель": "customer",
    "изготовитель": "manufacturer",
    "производитель": "manufacturer",
    "завод": "manufacturer",
    "дилер": "dealer",
    "поставщик": "dealer",
    "орган по сертификации": "certification_body",
    "испытательный центр": "testing_center",
    "испытательная лаборатория": "testing_center",
}

_ORG_TYPE_KEYWORDS: list[tuple[OrgType, re.Pattern[str]]] = [
    ("testing_center", re.compile(r"испытательн\w+\s+(?:центр|лаборатор)", re.I)),
    ("certification_body", re.compile(r"орган\w*\s+по\s+сертификац", re.I)),
    ("dealer", re.compile(r"\bдилер\w*\b", re.I)),
    ("manufacturer", re.compile(r"(?:кабельн\w+\s+завод|завод\w*|производител\w*|изготовител\w*)", re.I)),
]

_FSA_PATTERN = re.compile(
    r"РОСС\s*RU\.\d{4}\.\d{2}[A-ZА-Я0-9]+",
    re.IGNORECASE,
)
_INN_KPP_PATTERN = re.compile(
    r"ИНН\s*/?\s*КПП\s*(\d{10,12})\s*/\s*(\d{9})",
    re.IGNORECASE,
)
_INN_ONLY_PATTERN = re.compile(r"ИНН\s*(\d{10,12})", re.IGNORECASE)
_POSTAL_CODE_PATTERN = re.compile(r"\b(\d{6})\b")
_PHONE_PATTERN = re.compile(
    r"(?:Тел|Tex|тел|т/ф|Факс|факс)\s*[.:]?\s*(\+?\d[\d\s\(\)\-]{9,35})",
    re.IGNORECASE,
)
_EMAIL_PATTERN = re.compile(
    r"(?:E-?mail|электронн\w*\s*почт\w*)\s*[.:]?\s*([\w.\-]+@[\w.\-]+\.\w+)",
    re.IGNORECASE,
)
_OOO_NAME_PATTERN = re.compile(
    r"(?:ООО|Общество\s+[сc]\s+ограниченной\s+ответственностью)\s*"
    r"[{«\"'(\[]?([^}\»\"'\]\d]{4,90})",
    re.IGNORECASE,
)
_QUOTED_NAME_PATTERN = re.compile(
    r"[«\"']([^»\"']{4,80}(?:завод|кабель|завод\w*|центр|лаборатор\w*))[»\"']",
    re.IGNORECASE,
)
_HEADER_CAPS_PATTERN = re.compile(
    r"^([А-ЯЁA-Z][А-ЯЁA-Z\s\-]{8,60}(?:ЗАВОД|КАБЕЛ\w*|ЦЕНТР))",
    re.MULTILINE,
)

_ADDRESS_STOP_MARKERS = (
    "НАПРАВЛЕНИЕ",
    "Наименование и адрес",
    "HanmeHosaunre",
    "Mapka O6o3HayeHne",
    "Прошу провести",
    "Прош у провести",
    "№ п/п",
    "№ Наименование",
    "Образцы представлены",
    "Испытания следует",
    "Изготовитель:",
    "Дополнительная информация",
    "Допо лнительная информация",
    "Серийный выпуск",
    "Эксперт",
    "Эксп ерт",
    "т/ф ",
    "тел.",
    "ИНН",
    "WHH",
    "ОГРН",
    "OfPH",
    "р/с",
    "p/c",
    "1p/c",
    "BUK",
    "Ka6eAb",
    "BBI-",
    "ВВГ",
    "ПВСнг",
    "NBCur",
    "Nposoa",
)

_KALUGA_POSTAL = "249841"
_KALUGA_CANONICAL_ADDRESS = (
    "249841, Калужская область, Дзержинский район, "
    "д. Жилетово, ул. Промышленная, д. 1, стр. 5"
)

_CABLE_MARK_IN_ADDRESS = re.compile(
    r"(?:ВВГ|ПВСнг|ПВС-|АПуВ\s+\d|ПБГВВ|BBI-|NBCur|Mapka\s|"
    r"HanmeHosa|\d+\s*[хx]\s*[\d.,]+(?:ок|\(N))",
    re.IGNORECASE,
)

_KALUGA_ADDRESS_BLOCK = re.compile(
    rf"{_KALUGA_POSTAL}\s*,\s*(.+?)(?=\s*(?:1p/c|p/c|р/с|BUK|WHH|ИНН|Ka6eAb|"
    rf"HanmeHosa|Mapka|BBI-|NMpocum)\b)",
    re.IGNORECASE | re.DOTALL,
)


def normalize_org_name(name: str) -> str:
    """Ключ для дедупликации организаций."""
    name = name.lower().strip()
    name = re.sub(r"[«»\"'`{}\[\]]", "", name)
    name = re.sub(r"\s+", " ", name)
    for prefix in (
        "общество с ограниченной ответственностью",
        "ооо",
        "ао",
        "пао",
        "зао",
    ):
        if name.startswith(prefix + " "):
            name = name[len(prefix) + 1 :]
    return name.strip(" .,;-")


def fix_ocr_address_text(raw: str) -> str:
    """Латиница→кириллица и типовые подмены OCR в адресе (шапка письма)."""
    text = raw.replace("\n", " ")
    text = re.sub(r"Poccumickaa\s+Peaepauna,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"KaAyKCKaA\s+OOACCTE", "Калужская область", text, flags=re.IGNORECASE)
    text = re.sub(r"A3@PXXUHCKMM\s+PANOH", "Дзержинский район", text, flags=re.IGNORECASE)
    text = re.sub(r"A\.\s*Kuaetoso", "д. Жилетово", text, flags=re.IGNORECASE)
    text = re.sub(r"\bKuaetoso\b", "Жилетово", text, flags=re.IGNORECASE)
    text = re.sub(r"YA\.\s*MpOMbiLuAeHHas", "ул. Промышленная", text, flags=re.IGNORECASE)
    text = re.sub(r"\bYA\.\s*", "ул. ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bA\.\s*(\d+)\b", r"д. \1", text)
    text = re.sub(r"\bCTP\.\s*(\d+)\b", r"стр. \1", text, flags=re.IGNORECASE)
    return text


def _fix_kaluga_settlement_errors(text: str) -> str:
    """OCR иногда подменяет «д. Жилетово» (Kuaetoso) на «п. Киевский»."""
    if _KALUGA_POSTAL not in text and "Дзержинск" not in text:
        return text
    text = re.sub(r"п\.\s*Киевск\w*", "д. Жилетово", text, flags=re.IGNORECASE)
    text = re.sub(r"д\.\s*Киевск\w*", "д. Жилетово", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![\w-])Киевск\w*(?![\w-])", "Жилетово", text, flags=re.IGNORECASE)
    return text


def _is_kaluga_cable_factory(name: str, source_text: str = "") -> bool:
    if "калужск" in name.lower() and "кабельн" in name.lower():
        return True
    if source_text:
        return bool(
            re.search(
                r"KaayxKckni\s+KaGeAbHbIN|Калужск\w+\s+кабельн",
                source_text[:2500],
                re.IGNORECASE,
            )
        )
    return False


def _looks_like_cable_marks(text: str) -> bool:
    """Адрес не должен содержать условные обозначения кабелей."""
    if _CABLE_MARK_IN_ADDRESS.search(text):
        return True
    lines = [ln.strip() for ln in re.split(r"[\n;]+", text) if ln.strip()]
    if len(lines) >= 2:
        hits = sum(
            1
            for ln in lines
            if re.search(r"(?:ВВГ|ПВС|АПуВ|ПБГВВ).*\d+\s*[хx]", ln, re.IGNORECASE)
        )
        if hits >= 2:
            return True
    return False


def normalize_address_text(raw: str) -> str:
    """Сжимает пробелы и правит типичные OCR-ошибки в адресе."""
    text = fix_ocr_address_text(raw)
    text = _fix_kaluga_settlement_errors(text)
    text = re.sub(r"\s+", " ", text).strip(" .,;")
    text = re.sub(r"С\s+анкт", "Санкт", text, flags=re.IGNORECASE)
    text = re.sub(r"Р\s+ОССИЯ", "РОССИЯ", text, flags=re.IGNORECASE)
    if text.startswith(f"{_KALUGA_POSTAL},"):
        text = re.sub(r",\s*1\s*$", "", text)
    return text


_KALUGA_LATIN_ADDRESS = re.compile(
    r"249841.*(?:Poccumickaa|KaAyKCKaA|A3@PXXUHCKMM|Kuaetoso|MpOMbiLuAeHHas)",
    re.IGNORECASE,
)


def finalize_organization_address(
    org: OrganizationExtract,
    source_text: str = "",
) -> OrganizationExtract:
    """Нормализует адрес организации после OCR (кириллица, Калужа)."""
    name_low = org.name.lower()
    raw_addr = org.legal_address or org.address or ""
    if _is_kaluga_cable_factory(org.name, source_text):
        preferred: str | None = None
        if source_text:
            preferred = extract_kaluga_factory_address(source_text)
        if not preferred and raw_addr:
            if re.search(r"Киевск", raw_addr, re.IGNORECASE) or (
                _KALUGA_POSTAL in raw_addr
                and "Промышленная" in raw_addr
                and "Жилетово" not in raw_addr
            ):
                preferred = _KALUGA_CANONICAL_ADDRESS
            else:
                preferred = sanitize_address(raw_addr) or normalize_address_text(raw_addr)
        if preferred and not _looks_like_cable_marks(preferred):
            postal = _postal_from_address(preferred) or org.postal_code or _KALUGA_POSTAL
            return org.model_copy(
                update={
                    "address": preferred,
                    "legal_address": preferred,
                    "actual_address": org.actual_address or preferred,
                    "postal_code": postal,
                }
            )
    if not raw_addr:
        if source_text and (
            "калужск" in name_low
            or re.search(r"KaayxKckni\s+KaGeAbHbIN", source_text[:2500], re.I)
        ):
            fixed = extract_kaluga_factory_address(source_text)
            if fixed:
                return org.model_copy(
                    update={
                        "address": fixed,
                        "legal_address": fixed,
                        "actual_address": fixed,
                        "postal_code": _KALUGA_POSTAL,
                    }
                )
        return org

    if _KALUGA_LATIN_ADDRESS.search(raw_addr) or (
        "калужск" in name_low and re.search(r"[A-Za-z]{4,}", raw_addr)
    ):
        fixed = extract_kaluga_factory_address(source_text or raw_addr) or normalize_address_text(
            raw_addr
        )
    else:
        fixed = sanitize_address(raw_addr) or normalize_address_text(raw_addr)

    if not fixed or _looks_like_cable_marks(fixed):
        return org

    postal = _postal_from_address(fixed) or org.postal_code
    return org.model_copy(
        update={
            "address": fixed,
            "legal_address": fixed,
            "actual_address": org.actual_address or fixed,
            "postal_code": postal,
        }
    )


def finalize_organizations(
    organizations: list[OrganizationExtract],
    source_text: str = "",
) -> list[OrganizationExtract]:
    return [finalize_organization_address(org, source_text) for org in organizations]


def sanitize_address(address: str | None, *, max_len: int = 220) -> str | None:
    """
    Обрезает «хвост» адреса, если в поле попал текст всего документа.
    Возвращает только осмысленную часть адреса.
    """
    if not address or not str(address).strip():
        return None
    if _looks_like_cable_marks(str(address)):
        return None
    text = normalize_address_text(str(address))
    if _looks_like_cable_marks(text):
        return None
    if len(text) < 8:
        return None

    upper = text.upper()
    cut_at = len(text)
    for marker in _ADDRESS_STOP_MARKERS:
        idx = upper.find(marker.upper())
        if idx > 15:
            cut_at = min(cut_at, idx)
    text = text[:cut_at].strip(" .,;")

    if len(text) > max_len:
        parts = [normalize_address_text(p) for p in text.split(";") if p.strip()]
        parts = [p for p in parts if _POSTAL_CODE_PATTERN.search(p)]
        if parts:
            text = parts[0]
        else:
            text = text[:max_len].rsplit(" ", 1)[0].strip(" .,;")

    return text if len(text) >= 8 else None


def _postal_from_address(address: str | None) -> str | None:
    if not address:
        return None
    match = _POSTAL_CODE_PATTERN.search(address)
    return match.group(1) if match else None


def _extract_labeled_address(text: str, labels: tuple[str, ...], *, stop_before: str) -> str | None:
    for label in labels:
        pattern = re.compile(
            rf"{label}\s*[:\-]?\s*(.+?)(?={stop_before})",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(text[:6000])
        if not match:
            continue
        addr = sanitize_address(match.group(1))
        if addr:
            return addr
    return None


def extract_customer_addresses(text: str) -> tuple[str | None, str | None]:
    """Юридический и фактический адрес заказчика из шапки документа."""
    stop = (
        r"(?:Адрес\s+места\s+осуществления|т/ф|Тел|тел|НАПРАВЛЕНИЕ|"
        r"Наименование\s+и\s+адрес|№\s+Наименование|Изготовитель\s*:|$)"
    )
    legal = _extract_labeled_address(
        text,
        ("Место нахождения", "юридический адрес", "Юридический адрес"),
        stop_before=stop,
    )
    actual = _extract_labeled_address(
        text,
        ("Адрес места осуществления деятельности", "фактический адрес", "Фактический адрес"),
        stop_before=(
            r"(?:т/ф|Тел|тел|НАПРАВЛЕНИЕ|Наименование\s+и\s+адрес|"
            r"№\s+Наименование|Изготовитель\s*:|$)"
        ),
    )
    if actual and ";" in actual:
        actual = sanitize_address(actual.split(";")[0])
    return legal, actual


def extract_manufacturer_details(text: str) -> tuple[str | None, str | None]:
    """Изготовитель и его адрес из блока «Изготовитель:»."""
    pattern = re.compile(
        r"Изготовитель\s*:\s*(.+?)(?:\n|\r)([\d\D]+?)"
        r"(?=\n\s*(?:Серийный\s+выпуск|Код\s*\(|Допо|Эксп|$))",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None, None

    name_raw = match.group(1).strip().strip('"«»')
    name = _clean_org_name(_fix_ocr_name(name_raw))
    if '"' in name_raw and not name.endswith('"'):
        name = name + '"'
    if len(normalize_org_name(name)) < 4:
        return None, None

    addr_raw = match.group(2).strip()
    addr = sanitize_address(addr_raw)
    if not addr and _POSTAL_CODE_PATTERN.search(addr_raw):
        addr = sanitize_address(_POSTAL_CODE_PATTERN.sub(r"\1, ", addr_raw, count=1))

    return name, addr


def resolve_org_addresses(org: dict | OrganizationExtract | None) -> tuple[str, str]:
    """
    Возвращает (юридический, фактический) адрес организации для формы заявки.
    """
    if not org:
        return "—", "—"

    if isinstance(org, OrganizationExtract):
        legal = sanitize_address(org.legal_address) or sanitize_address(org.address)
        actual = sanitize_address(org.actual_address) or legal
    else:
        legal = (
            sanitize_address(org.get("legal_address"))
            or sanitize_address(org.get("address"))
        )
        actual = sanitize_address(org.get("actual_address")) or legal

    return legal or "—", actual or "—"


def _clean_org_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw).strip(" .,;:{}\"")

    name = re.sub(r"(?:л|1)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\d{6}.*$", "", name)
    name = re.sub(r"\s+(?:российская|рф|россия).*$", "", name, flags=re.IGNORECASE)

    if re.search(r"АКЦИОНЕРНОЕ\s+ОБЩЕСТВО|АО\s*«", name, re.IGNORECASE):
        return name.strip()

    if name and not name.upper().startswith("ООО"):
        short = name.strip()
        if len(short) >= 4:
            return f'ООО «{short}»'
    if "«" not in name and "»" not in name:
        core = re.sub(r"^ООО\s+", "", name, flags=re.IGNORECASE).strip()
        if core:
            return f"ООО «{core}»"
    return name


def _fix_ocr_name(name: str) -> str:
    """Поправки типичных OCR-ошибок в названии завода."""
    fixes = (
        (r"КААУЖСК", "Калужск"),
        (r"кабеАьн", "кабельн"),
        (r"кабеаьн", "кабельн"),
        (r"ХАВOА", "завод"),
        (r"ХАВОА", "завод"),
        (r"Ка\^ужск", "Калужск"),
        (r"заводл", "завод"),
    )
    for pattern, repl in fixes:
        name = re.sub(pattern, repl, name, flags=re.IGNORECASE)
    return name


def _infer_org_type(text: str, name: str) -> OrgType:
    blob = f"{name}\n{text[:2500]}"
    for org_type, pattern in _ORG_TYPE_KEYWORDS:
        if pattern.search(blob):
            return org_type
    if re.search(r"кабельн\w+|завод", name, re.I):
        return "manufacturer"
    return "unknown"


def _extract_name(text: str) -> str | None:
    header = text[:2000]
    for pattern in (_OOO_NAME_PATTERN, _QUOTED_NAME_PATTERN, _HEADER_CAPS_PATTERN):
        match = pattern.search(header)
        if match:
            raw = _fix_ocr_name(match.group(1))
            name = _clean_org_name(raw)
            if len(normalize_org_name(name)) >= 4:
                return name
    return None


def _extract_labeled_org(text: str, label: str) -> OrganizationExtract | None:
    pattern = re.compile(
        rf"{label}\s*[:\-]\s*(.+?)(?=\n|заказчик|изготовитель|производитель|марка|№|$)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    chunk = match.group(1).strip()[:300]
    name = _clean_org_name(_fix_ocr_name(chunk.split(",")[0]))
    if len(normalize_org_name(name)) < 4:
        return None
    return OrganizationExtract(
        name=name,
        org_type=_infer_org_type(text, name),
        role=_ROLE_LABELS.get(label.lower(), "unknown"),
        confidence=0.75,
    )


def _build_org_from_header(text: str) -> OrganizationExtract | None:
    name = _extract_name(text)
    if not name:
        return None

    inn = kpp = None
    inn_match = _INN_KPP_PATTERN.search(text[:3000])
    if inn_match:
        inn, kpp = inn_match.group(1), inn_match.group(2)
    else:
        solo = _INN_ONLY_PATTERN.search(text[:3000])
        if solo:
            inn = solo.group(1)

    legal_address, actual_address = extract_customer_addresses(text)
    address = legal_address
    postal_code = _postal_from_address(legal_address or actual_address)

    phone = None
    phone_match = _PHONE_PATTERN.search(text[:4000])
    if phone_match:
        phone = re.sub(r"\s+", " ", phone_match.group(1)).strip()

    email = None
    email_match = _EMAIL_PATTERN.search(text[:3000])
    if email_match:
        email = email_match.group(1).replace(" ", "")

    fsa = None
    fsa_match = _FSA_PATTERN.search(text[:2500])
    if fsa_match:
        fsa = fsa_match.group(0).upper().replace("  ", " ")

    is_accredited = bool(fsa) or bool(
        re.search(r"аккредитован\w*", text[:4000], re.IGNORECASE)
    )

    org_type = _infer_org_type(text, name)
    if org_type == "unknown" and re.search(r"завод|кабель", name, re.I):
        org_type = "manufacturer"

    confidence = 0.5
    if inn:
        confidence += 0.2
    if postal_code:
        confidence += 0.1
    if legal_address:
        confidence += 0.15

    return OrganizationExtract(
        name=name,
        address=address,
        legal_address=legal_address,
        actual_address=actual_address,
        postal_code=postal_code,
        phone=phone,
        email=email,
        inn=inn,
        kpp=kpp,
        is_accredited=is_accredited,
        fsa_registry_number=fsa,
        org_type=org_type,
        role="unknown",
        confidence=min(confidence, 0.95),
    )


def extract_kaluga_factory_address(text: str) -> str | None:
    """Адрес ООО «Калужский кабельный завод» из шапки письма (OCR)."""
    if not re.search(r"KaayxKckni\s+KaGeAbHbIN|Калужск\w+\s+кабельн", text[:2500], re.I):
        return None
    block = _KALUGA_ADDRESS_BLOCK.search(text[:2500])
    if block:
        raw = f"{_KALUGA_POSTAL}, {block.group(1)}"
        cleaned = sanitize_address(raw)
        if cleaned and not _looks_like_cable_marks(cleaned):
            return cleaned
    postal = re.search(rf"\b{_KALUGA_POSTAL}\b", text[:2500])
    if postal:
        chunk = text[postal.start() : postal.start() + 180]
        cleaned = sanitize_address(chunk)
        if cleaned and not _looks_like_cable_marks(cleaned):
            return cleaned
    return _KALUGA_CANONICAL_ADDRESS


def extract_organizations(text: str) -> list[OrganizationExtract]:
    """
    Извлекает организации из текста заявки.

    Возвращает заказчика, производителя и отправителя письма (шапка).
    Отправитель письма с запросом испытаний обычно совпадает с заказчиком.
    """
    if not text or not text.strip():
        return []

    from .letter_extractor import is_business_letter, organizations_from_letter
    from ..nlp.nlp_extractor import enhance_organizations

    if is_business_letter(text):
        letter_orgs = organizations_from_letter(text)
        if letter_orgs:
            return enhance_organizations(text, letter_orgs)

    found: list[OrganizationExtract] = []
    seen: set[str] = set()

    def add(org: OrganizationExtract | None, default_role: OrganizationRole) -> None:
        if not org or not org.name:
            return
        key = normalize_org_name(org.name)
        if not key or key in seen:
            return
        seen.add(key)
        if org.role == "unknown":
            org.role = default_role
        found.append(org)

    for label, role in _ROLE_LABELS.items():
        labeled = _extract_labeled_org(text, label)
        if labeled:
            labeled.role = role
            add(labeled, role)

    header_org = _build_org_from_header(text)
    if header_org:
        add(header_org, "customer")

    mfg_name, mfg_addr = extract_manufacturer_details(text)
    if mfg_name:
        mfg_key = normalize_org_name(mfg_name)
        found = [
            org
            for org in found
            if not (
                org.role == "manufacturer"
                and mfg_key
                and (
                    normalize_org_name(org.name) == mfg_key
                    or normalize_org_name(org.name) in mfg_key
                    or mfg_key in normalize_org_name(org.name)
                )
            )
        ]
        if mfg_key in seen:
            seen.discard(mfg_key)
        manufacturer = OrganizationExtract(
            name=mfg_name,
            address=mfg_addr,
            legal_address=mfg_addr,
            actual_address=mfg_addr,
            postal_code=_postal_from_address(mfg_addr),
            org_type="manufacturer",
            role="manufacturer",
            confidence=0.85 if mfg_addr else 0.7,
        )
        add(manufacturer, "manufacturer")

    if not found and header_org:
        manufacturer = header_org.model_copy(deep=True)
        manufacturer.role = "manufacturer"
        add(manufacturer, "manufacturer")

    if len(found) == 1 and found[0].role == "customer":
        manufacturer = found[0].model_copy(deep=True)
        manufacturer.role = "manufacturer"
        if normalize_org_name(manufacturer.name) not in seen:
            seen.add(normalize_org_name(manufacturer.name))
            found.append(manufacturer)

    found = finalize_organizations(found, text)
    return enhance_organizations(text, found)


def pick_customer_name(organizations: list[OrganizationExtract]) -> str:
    for org in organizations:
        if org.role == "customer" and org.name:
            return org.name
    for org in organizations:
        if org.role in ("manufacturer", "unknown") and org.name:
            return org.name
    return ""


def pick_manufacturer_name(organizations: list[OrganizationExtract]) -> str:
    for org in organizations:
        if org.role == "manufacturer" and org.name:
            return org.name
    for org in organizations:
        if org.org_type == "manufacturer" and org.name:
            return org.name
    return pick_customer_name(organizations)