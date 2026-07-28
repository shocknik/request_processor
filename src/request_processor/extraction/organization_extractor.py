"""
Извлечение сведений об организациях из текста заявок и писем (PDF/OCR/Word).
"""

from __future__ import annotations

import re
from pathlib import Path
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
    # тип (OS/ИЛ) задаётся org_type; role — customer/manufacturer/unknown
    "орган по сертификации": "customer",
    "испытательный центр": "unknown",
    "испытательная лаборатория": "unknown",
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
    "Цель проведения",
    "Представленная заказчиком",
    "(полное наименование",
    "Адрес места осуществления",
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

# Гео/бренды других заводов — не путать с бланком «Кабельный завод» (периодика, Калуга).
_OTHER_CABLE_PLANT_HINT = re.compile(
    r"тольят|тольятт|самарск|кирск|москв|петербург|ленинград|новосибир|"
    r"екатерин|челябин|воронеж|нижегород|казан|перм|краснодар|ростов|"
    r"волгоград|иркут|омск|тул[аы]|рязан|твер|белгород|липецк|"
    r"энергокомплект|спецкабель|витебск|белорус|минск|урал|"
    r"северн\w*\s+(?:ул|улиц)|северная",
    re.IGNORECASE,
)

# OCR-имя именно Калужского бланка (не «любой кабельный завод»).
_PERIODIC_FACTORY_OCR_NAME = re.compile(
    r"KaayxKckni\s+KaGeAbHbIN",
    re.IGNORECASE,
)

def _load_periodic_factory_profile() -> tuple[str, str]:
    """Почтовый индекс и канонический адрес завода для писем периодических испытаний.

    Реальные значения — только в ``data/client_profiles.local.yaml`` (gitignored).
    Без файла профиль пустой: адрес берётся из OCR-текста без принудительной подстановки.
    """
    try:
        import yaml
        from ..config import DATA_DIR

        path = DATA_DIR / "client_profiles.local.yaml"
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            prof = data.get("periodic_factory") or {}
            postal = str(prof.get("postal_code") or "").strip()
            address = str(prof.get("canonical_address") or "").strip()
            return postal, address
    except Exception:
        pass
    return "", ""


_PERIODIC_FACTORY_POSTAL, _PERIODIC_FACTORY_CANONICAL_ADDRESS = _load_periodic_factory_profile()

_CABLE_MARK_IN_ADDRESS = re.compile(
    r"(?:ВВГ|ПВСнг|ПВС-|АПуВ\s+\d|ПБГВВ|BBI-|NBCur|Mapka\s|"
    r"HanmeHosa|\d+\s*[хx]\s*[\d.,]+(?:ок|\(N))",
    re.IGNORECASE,
)

_PERIODIC_FACTORY_ADDRESS_BLOCK = (
    re.compile(
        rf"{re.escape(_PERIODIC_FACTORY_POSTAL)}\s*,\s*(.+?)(?=\s*(?:1p/c|p/c|р/с|BUK|WHH|ИНН|Ka6eAb|"
        rf"HanmeHosa|Mapka|BBI-|NMpocum)\b)",
        re.IGNORECASE | re.DOTALL,
    )
    if _PERIODIC_FACTORY_POSTAL
    else re.compile(r"(?!x)x")  # never matches without local profile
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
    from .ocr_text_normalizer import normalize_ocr_text

    return normalize_ocr_text(raw.replace("\n", " "))


def _fix_periodic_settlement_errors(text: str) -> str:
    """Коррекция OCR-ошибок н.п., если задан локальный профиль завода."""
    if not _PERIODIC_FACTORY_POSTAL or _PERIODIC_FACTORY_POSTAL not in text:
        return text
    if _PERIODIC_FACTORY_CANONICAL_ADDRESS:
        m = re.search(r"д\.\s*([^,]+)", _PERIODIC_FACTORY_CANONICAL_ADDRESS)
        settlement = m.group(1).strip() if m else ""
        if settlement:
            text = re.sub(r"п\.\s*Киевск\w*", f"д. {settlement}", text, flags=re.IGNORECASE)
            text = re.sub(r"д\.\s*Киевск\w*", f"д. {settlement}", text, flags=re.IGNORECASE)
            text = re.sub(r"(?<![\w-])Киевск\w*(?![\w-])", settlement, text, flags=re.IGNORECASE)
    return text


def _name_has_other_cable_plant_hint(name: str) -> bool:
    """True, если название явно другого завода (Тольятти, Кирскабель, …)."""
    if not name:
        return False
    return bool(_OTHER_CABLE_PLANT_HINT.search(name))


def _is_generic_or_kaluga_cable_factory_name(name: str) -> bool:
    """
    Имя «того» завода с бланка периодики: голое «Кабельный завод» / Калужский / OCR.

    Не матчит «Тольяттинский кабельный завод», «Кирскабель» и т.п.
    """
    if not name or not str(name).strip():
        return False
    if _name_has_other_cable_plant_hint(name):
        return False
    if _PERIODIC_FACTORY_OCR_NAME.search(name):
        return True
    low = normalize_org_name(name)
    if not low:
        return False
    if re.search(r"калужск", low):
        return "кабельн" in low or "завод" in low
    # Только «кабельный завод» / «ооо кабельный завод» без города/бренда.
    return bool(re.fullmatch(r"(?:ооо\s+)?кабельн\w*\s+завод\w*", low))


def _source_looks_like_periodic_factory_letter(source_text: str) -> bool:
    """Сильные признаки письма периодики Калужского завода (не любой документ с «завод»)."""
    if not source_text or not str(source_text).strip():
        return False
    head = source_text[:2500]
    if _PERIODIC_FACTORY_OCR_NAME.search(head):
        return True
    if _PERIODIC_FACTORY_POSTAL and re.search(rf"\b{re.escape(_PERIODIC_FACTORY_POSTAL)}\b", head):
        return True
    if re.search(r"калужск\w*\s+кабельн\w*\s+завод", head, re.IGNORECASE):
        return True
    if re.search(r"жилетово|Kuaetoso", head, re.IGNORECASE) and re.search(
        r"промышленная|MpOMbiLuAeHHas|кабельн\w*\s+завод",
        head,
        re.IGNORECASE,
    ):
        return True
    return False


def _is_periodic_letter_factory(name: str, source_text: str = "") -> bool:
    """
    True только для бланка периодики «Кабельный завод» (Калуга / OCR).

    Важно: наличие в тексте документа «…кабельный завод…» само по себе
    не делает *каждую* организацию «периодическим заводом» (см. направления
    с Тольяттинским КЗ, ОС ЦЭТИ и т.д.).
    """
    if _name_has_other_cable_plant_hint(name):
        return False
    if _is_generic_or_kaluga_cable_factory_name(name):
        return True
    # Имя без «кабельный завод», но OCR-шапка именно Калуги — не трогаем чужие org.
    # source_text здесь только как доп. подтверждение для generic-имени (уже выше).
    _ = source_text  # сохранён в сигнатуре для совместимости вызовов
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
    text = _fix_periodic_settlement_errors(text)
    text = re.sub(r"\s+", " ", text).strip(" .,;")
    text = re.sub(r"С\s+анкт", "Санкт", text, flags=re.IGNORECASE)
    text = re.sub(r"Р\s+ОССИЯ", "РОССИЯ", text, flags=re.IGNORECASE)
    if text.startswith(f"{_PERIODIC_FACTORY_POSTAL},"):
        text = re.sub(r",\s*1\s*$", "", text)
    return text


_PERIODIC_FACTORY_LATIN_ADDRESS = re.compile(
    r"(?:Poccumickaa|KaAyKCKaA|A3@PXXUHCKMM|Kuaetoso|MpOMbiLuAeHHas)",
    re.IGNORECASE,
)


def finalize_organization_address(
    org: OrganizationExtract,
    source_text: str = "",
) -> OrganizationExtract:
    """Нормализует адрес организации после OCR (кириллица, адрес завода)."""
    raw_addr = org.legal_address or org.address or ""
    is_periodic = _is_periodic_letter_factory(org.name, source_text)

    if is_periodic:
        preferred: str | None = None
        if source_text:
            preferred = extract_periodic_factory_address(source_text)
        if not preferred and raw_addr:
            if re.search(r"Киевск", raw_addr, re.IGNORECASE) or (
                _PERIODIC_FACTORY_POSTAL
                and _PERIODIC_FACTORY_POSTAL in raw_addr
                and "Промышленная" in raw_addr
            ):
                preferred = _PERIODIC_FACTORY_CANONICAL_ADDRESS or None
            else:
                preferred = sanitize_address(raw_addr) or normalize_address_text(raw_addr)
        if preferred and not _looks_like_cable_marks(preferred):
            postal = (
                _postal_from_address(preferred)
                or org.postal_code
                or (_PERIODIC_FACTORY_POSTAL or None)
            )
            return org.model_copy(
                update={
                    "address": preferred,
                    "legal_address": preferred,
                    "actual_address": org.actual_address or preferred,
                    "postal_code": postal,
                }
            )

    if not raw_addr:
        # Пустой адрес: подставляем профиль только для *этого* завода, не для любого КЗ.
        if is_periodic and source_text:
            fixed = extract_periodic_factory_address(source_text)
            if fixed:
                return org.model_copy(
                    update={
                        "address": fixed,
                        "legal_address": fixed,
                        "actual_address": fixed,
                        "postal_code": _PERIODIC_FACTORY_POSTAL or _postal_from_address(fixed),
                    }
                )
        return org

    # Латиница OCR / профиль — только если это действительно бланк периодики
    # или в самом адресе уже признаки Калуги (индекс/латиница шапки).
    looks_latin_factory = bool(_PERIODIC_FACTORY_LATIN_ADDRESS.search(raw_addr))
    if is_periodic and (looks_latin_factory or re.search(r"[A-Za-z]{4,}", raw_addr)):
        fixed = extract_periodic_factory_address(source_text or raw_addr) or normalize_address_text(
            raw_addr
        )
    elif looks_latin_factory and _source_looks_like_periodic_factory_letter(source_text or raw_addr):
        fixed = extract_periodic_factory_address(source_text or raw_addr) or normalize_address_text(
            raw_addr
        )
    else:
        fixed = sanitize_address(raw_addr) or normalize_address_text(raw_addr)

    if not fixed or _looks_like_cable_marks(fixed):
        return org

    postal = _postal_from_address(fixed) or org.postal_code
    # Не перетираем чужой actual_address «каноном» — только нормализуем address/legal.
    actual = org.actual_address
    if actual:
        actual_clean = sanitize_address(actual)
        actual = actual_clean or actual
    else:
        actual = fixed

    return org.model_copy(
        update={
            "address": fixed,
            "legal_address": fixed,
            "actual_address": actual,
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

    # Снять подписи полей из направлений/актов: «Место нахождения (…): 445043, …»
    text = re.sub(
        r"^(?:Место\s+нахождения|Адрес\s+места\s+осуществления|"
        r"юридический\s+адрес|фактический\s+адрес)"
        r"[^:]{0,80}:\s*",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    upper = text.upper()
    cut_at = len(text)
    for marker in _ADDRESS_STOP_MARKERS:
        idx = upper.find(marker.upper())
        # idx > 8: индекс/город уже могут быть короче 15 символов
        if idx > 8:
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


def is_act_document(text: str) -> bool:
    """Акт отбора образцов (заявитель в отдельном блоке)."""
    if not text or not text.strip():
        return False
    return bool(re.search(r"АКТ\s+отбора\s+образц", text, re.I))


def extract_applicant_details(text: str) -> tuple[str | None, str | None]:
    """Заявитель из блока «Наименование и адрес заявителя» (акт отбора)."""
    pattern = re.compile(
        r"Наименование\s+и\s+адрес\s+заявителя\s*:\s*(.+?)\n"
        r"([\d\D]+?)(?=Мес\s*то\s+отбора|Место\s+отбора|№\s+Наименование|$)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None, None

    name_raw = match.group(1).strip().strip('"«»')
    name = _clean_org_name(_fix_ocr_name(name_raw))
    if len(normalize_org_name(name)) < 4:
        return None, None

    addr = sanitize_address(match.group(2).strip())
    return name, addr


def extract_manufacturer_details(text: str) -> tuple[str | None, str | None]:
    """Изготовитель и его адрес из блока «Изготовитель:»."""
    pattern = re.compile(
        r"Изготовитель\s*:\s*(.+?)(?:\n|\r)([\d\D]+?)"
        r"(?=\n\s*(?:Серийный\s+выпуск|Код\s*\(|Допо|Эксп|Цель\s+проведения|$))",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None, None

    name_raw = match.group(1).strip().strip('"«»')
    name = _clean_org_name(_fix_ocr_name(name_raw))
    if len(normalize_org_name(name)) < 4:
        return None, None

    addr_raw = match.group(2).strip()
    # Предпочитаем явный юр. адрес из направления, а не весь хвост блока.
    labeled = re.search(
        r"(?:Место\s+нахождения|адрес\s+юридического\s+лица)\s*"
        r"(?:\([^)]{0,80}\))?\s*:\s*(.+?)"
        r"(?=\s*(?:Адрес\s+места|Цель\s+проведения|Представленная|"
        r"\(полное\s+наименование|Серийный\s+выпуск|$))",
        addr_raw,
        re.IGNORECASE | re.DOTALL,
    )
    if labeled:
        addr = sanitize_address(labeled.group(1).strip())
    else:
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


_FULL_OOO_FORM = re.compile(
    r"Общество\s+с\s+ограниченной\s+ответственностью",
    re.IGNORECASE,
)


def _clean_org_name(raw: str) -> str:
    """Нормализует название: полное «Общество…» → ООО, без двойного префикса."""
    name = re.sub(r"\s+", " ", raw).strip(" .,;:{}")
    # Снять внешние/внутренние ASCII-кавычки вокруг ядра («"ТОЛЬЯТТИ…» → «ТОЛЬЯТТИ…»).
    name = name.strip().strip('"«»\'')
    name = re.sub(r'[«"]\s*"', "«", name)
    name = re.sub(r'"\s*[»"]', "»", name)
    name = re.sub(r'"+', "", name)

    name = re.sub(r"(?:л|1)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\d{6}.*$", "", name)
    name = re.sub(r"\s+(?:российская|рф|россия).*$", "", name, flags=re.IGNORECASE)

    if re.search(r"АКЦИОНЕРНОЕ\s+ОБЩЕСТВО|АО\s*«", name, re.IGNORECASE):
        return name.strip()

    # «Общество с ограниченной ответственностью «X»» → «ООО «X»»
    # и снятие двойного «ООО «Общество…»»
    while True:
        collapsed = re.sub(
            rf"^(?:ООО\s*)?[«\"']?\s*{_FULL_OOO_FORM.pattern}\s*",
            "ООО ",
            name,
            count=1,
            flags=re.IGNORECASE,
        )
        collapsed = collapsed.strip().lstrip("«\"'").strip()
        if collapsed == name or not collapsed:
            break
        name = collapsed

    if name and not re.match(r"^(?:ООО|АО|ПАО|ЗАО)\b", name, re.IGNORECASE):
        short = name.strip().strip("«»\"'")
        if len(short) >= 4:
            return f"ООО «{short}»"
    if re.match(r"^ООО\b", name, re.IGNORECASE) and "«" not in name and "»" not in name:
        core = re.sub(r"^ООО\s+", "", name, flags=re.IGNORECASE).strip().strip("«»\"'")
        if core:
            return f"ООО «{core}»"
    # убрать ««…»» после склейки
    name = re.sub(r"«\s*«", "«", name)
    name = re.sub(r"»\s*»", "»", name)
    if re.match(r"^ООО\b", name, re.IGNORECASE) and not name.startswith("ООО «"):
        core = re.sub(r"^ООО\s+", "", name, flags=re.IGNORECASE).strip().strip("«»\"'")
        if core:
            return f"ООО «{core}»"
    # Финальная зачистка: ООО «"X"» / ООО «X»"
    name = re.sub(r"«\s*[\"']+", "«", name)
    name = re.sub(r"[\"']+\s*»", "»", name)
    name = re.sub(r"[\"']+$", "", name)
    return name.strip()


def _fix_ocr_name(name: str) -> str:
    """Поправки типичных OCR-ошибок в названии завода."""
    fixes = (
        (r"КААУЖСК", "Кабельн"),
        (r"кабеАьн", "кабельн"),
        (r"кабеаьн", "кабельн"),
        (r"ХАВOА", "завод"),
        (r"ХАВОА", "завод"),
        (r"Ка\^ужск", "Кабельн"),
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


def _infer_header_org_type(text: str, name: str) -> OrgType:
    """Тип организации из шапки: орган по сертификации не путаем с ИЛ в теле направления."""
    head = text[:1500]
    if re.search(r"орган\w*\s+по\s+сертификац", head, re.I):
        return "certification_body"
    return _infer_org_type(text, name)


def is_direction_document(text: str) -> bool:
    """Направление в аккредитованную испытательную лабораторию."""
    if not text or not text.strip():
        return False
    return bool(
        re.search(r"НАПРАВЛЕНИЕ", text, re.I)
        and re.search(r"испытательн", text, re.I)
    )


# ИЛ не бывает «заказчиком» заявки к себе; ОС (certification_body) — наоборот, часто заказчик.
_NON_CUSTOMER_ORG_TYPES = frozenset({"testing_center"})


def _is_own_lab_org(org: OrganizationExtract | str) -> bool:
    """Наша ИЛ (lab_profile / Кабель-Тест) — не заказчик и не производитель."""
    try:
        from ..generation.lab_profile import is_own_lab_name
    except Exception:
        is_own_lab_name = None  # type: ignore[assignment]
    name = org if isinstance(org, str) else (org.name or "")
    if is_own_lab_name and is_own_lab_name(name):
        return True
    if re.search(r"кабель[\s\-–]*тест", name or "", re.I):
        return True
    return False


def _is_non_customer_org(org: OrganizationExtract) -> bool:
    """ИЛ / наша лаборатория не может быть заказчиком. ОС (ФаерЛаб) — может."""
    if _is_own_lab_org(org):
        return True
    if org.org_type in _NON_CUSTOMER_ORG_TYPES:
        return True
    name = org.name or ""
    if re.search(r"испытательн\w+\s+(?:центр|лаборатор)", name, re.I):
        return True
    return False


def extract_testing_center_from_direction(text: str) -> OrganizationExtract | None:
    """Испытательный центр из шапки направления в ИЛ."""
    match = re.search(
        r"Испытательный\s+центр\s+(.+?)"
        r"(?:,\s*уникальный\s+номер|,\s*аттестат|аттестат\s+аккредитации|"
        r"адрес\s*(?:места)?|Наименование\s+ИЛ|$)",
        text[:6000],
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        # fallback: НИЦ «Кабель-Тест» в начале документа
        nic = re.search(
            r'НИЦ\s*[«""]([^»"]+)[»""]',
            text[:2500],
            re.I,
        )
        if not nic:
            return None
        name = f'ООО НИЦ «{nic.group(1).strip()}»'
        fsa_m = _FSA_PATTERN.search(text[:2500])
        return OrganizationExtract(
            name=name,
            org_type="testing_center",
            role="unknown",
            is_accredited=bool(fsa_m),
            fsa_registry_number=(
                fsa_m.group(0).upper().replace("  ", " ") if fsa_m else None
            ),
            confidence=0.75,
        )

    chunk = match.group(1).strip()
    name: str | None = None
    nic = re.search(r'НИЦ\s*[«""]([^»"]+)[»""]', chunk, re.I)
    if nic:
        name = f'ООО НИЦ «{nic.group(1).strip()}»'
    else:
        ooo = re.search(r'ООО\s+[«""]([^»"]+)[»""]', chunk, re.I)
        if ooo:
            name = f'ООО «{ooo.group(1).strip()}»'
        else:
            short = re.sub(r"\s+", " ", chunk.split(",")[0]).strip()[:120]
            name = _clean_org_name(short) if short else None

    if not name or len(normalize_org_name(name)) < 4:
        return None

    tail = text[match.start() : match.start() + 900]
    addr = None
    addr_m = re.search(
        r"(\d{6}[^\n]{10,160})",
        tail,
        re.I,
    )
    if addr_m and not re.search(r"НАПРАВЛЕНИЕ|орган", addr_m.group(1), re.I):
        addr = sanitize_address(addr_m.group(1))

    fsa_m = _FSA_PATTERN.search(tail) or _FSA_PATTERN.search(text[:2500])
    phone = None
    phone_m = re.search(r"(\+?\d[\d\s\-]{9,20})", tail)
    if phone_m and len(re.sub(r"\D", "", phone_m.group(1))) >= 10:
        phone = re.sub(r"\s+", " ", phone_m.group(1)).strip()

    return OrganizationExtract(
        name=name,
        address=addr,
        legal_address=addr,
        actual_address=addr,
        postal_code=_postal_from_address(addr),
        phone=phone,
        org_type="testing_center",
        role="unknown",
        is_accredited=bool(fsa_m),
        fsa_registry_number=fsa_m.group(0).upper().replace("  ", " ") if fsa_m else None,
        confidence=0.8,
    )


def extract_certification_body_from_direction(text: str) -> OrganizationExtract | None:
    """
    Орган по сертификации из направления (заказчик для ИЛ).

    Пример:
      НАПРАВЛЕНИЕ
      Орган по сертификации Общества с ограниченной ответственностью «ФаерЛаб»
      ...
      Адрес места осуществления деятельности: 143985, … Телефон: … E-mail: …
    """
    if not text or not is_direction_document(text):
        return None

    head = text[:7000]
    name: str | None = None

    # 1) «Орган по сертификации … «ФаерЛаб»» (имя в той же фразе)
    m_quoted = re.search(
        r"Орган\w*\s+по\s+сертификац\w*\s+"
        r"(?:Общества\s+с\s+ограниченной\s+ответственностью\s+)?"
        r"[«\"']([^»\"']{2,80})[»\"']",
        head,
        re.IGNORECASE | re.DOTALL,
    )
    if m_quoted:
        brand = m_quoted.group(1).strip()
        # отсечь мусор: «продукции и услуг» без реального бренда
        if not re.search(r"продукц\w*\s+и\s+услуг", brand, re.I):
            name = f"ООО «{brand}»"

    # 2) Следующая строка — ООО «Тест-С.-Петербург»
    if not name:
        m_next = re.search(
            r"Орган\w*\s+по\s+сертификац\w*[^\n]{0,80}\n\s*"
            r"((?:ООО|Общество\s+с\s+ограниченной\s+ответственностью)"
            r"[^\n]{3,100})",
            head,
            re.IGNORECASE,
        )
        if m_next:
            raw = re.sub(r"\s+", " ", m_next.group(1)).strip()
            mq = re.search(r"[«\"']([^»\"']{2,80})[»\"']", raw)
            if mq and not re.search(r"продукц\w*\s+и\s+услуг", mq.group(1), re.I):
                name = f"ООО «{mq.group(1).strip()}»"
            else:
                cleaned = _clean_org_name(raw[:120])
                if (
                    len(normalize_org_name(cleaned)) >= 4
                    and not re.search(r"продукц\w*\s+и\s+услуг", cleaned, re.I)
                ):
                    name = cleaned

    # 3) Та же строка: Общество с ограниченной ответственностью «X»
    if not name:
        m_line = re.search(
            r"Орган\w*\s+по\s+сертификац\w*\s+"
            r"(Общества\s+с\s+ограниченной\s+ответственностью\s+[«\"'][^»\"']+[»\"']"
            r"|ООО\s+[«\"'][^»\"']+[»\"'])",
            head,
            re.IGNORECASE,
        )
        if m_line:
            raw = re.sub(r"\s+", " ", m_line.group(1)).strip()
            mq = re.search(r"[«\"']([^»\"']{2,80})[»\"']", raw)
            if mq:
                name = f"ООО «{mq.group(1).strip()}»"

    if not name or len(normalize_org_name(name)) < 3:
        return None
    if re.search(r"продукц\w*\s+и\s+услуг", name, re.I):
        return None

    # Блок реквизитов после «Адрес места осуществления деятельности»
    addr = phone = email = None
    block_m = re.search(
        r"Адрес\s+места\s+осуществления\s+деятельности\s*:\s*(.+?)"
        r"(?=направляет\s+образц|Эксперт\s+органа|Образцы\s+на\s+испытания|$)",
        head,
        re.IGNORECASE | re.DOTALL,
    )
    block = block_m.group(1) if block_m else ""
    if block:
        # отрезать служебную строку-подпись формы
        block = re.split(
            r"адрес\s+места\s+осуществления\s+деятельности\s*,\s*телефон",
            block,
            maxsplit=1,
            flags=re.I,
        )[0]
        # телефон / email вырезать из адреса
        email_m = re.search(
            r"(?:адрес\s+электронной\s+почты|e-?mail)\s*:\s*([\w.\-]+@[\w.\-]+\.\w+)",
            block,
            re.I,
        )
        if email_m:
            email = email_m.group(1).replace(" ", "")
        phone_m = re.search(
            r"Телефон\s*:\s*(\+?[\d\s\(\)\-]{7,30})",
            block,
            re.I,
        )
        if phone_m:
            phone = re.sub(r"\s+", " ", phone_m.group(1)).strip().rstrip(".,;")
        addr_raw = re.split(r"Телефон\s*:", block, maxsplit=1, flags=re.I)[0]
        addr_raw = re.sub(r"ОГРН\s*:\s*\d+", "", addr_raw, flags=re.I)
        addr = sanitize_address(addr_raw.strip(" \n\t.,;"))

    return OrganizationExtract(
        name=name,
        address=addr,
        legal_address=addr,
        actual_address=addr,
        postal_code=_postal_from_address(addr),
        phone=phone,
        email=email,
        org_type="certification_body",
        role="customer",
        confidence=0.9 if addr or phone or email else 0.8,
    )


def assign_organization_roles(
    organizations: list[OrganizationExtract],
    text: str,
) -> list[OrganizationExtract]:
    """Расставляет роли с учётом типа документа (направление в ИЛ и т.д.)."""
    if not organizations:
        return organizations

    result = [org.model_copy(deep=True) for org in organizations]

    for org in result:
        if _is_own_lab_org(org) or org.org_type == "testing_center":
            org.org_type = "testing_center"
            if org.role in ("customer", "manufacturer"):
                org.role = "unknown"
            continue
        if org.role == "customer" and _is_non_customer_org(org):
            org.role = "unknown"
            if re.search(r"сертификац", org.name or "", re.I):
                org.org_type = "certification_body"
            elif org.org_type != "certification_body":
                org.org_type = "testing_center"

    if not is_direction_document(text):
        return result

    # Направление: ОС = заказчик (если ещё не назначен)
    cert = next(
        (o for o in result if o.org_type == "certification_body" and o.name),
        None,
    )
    if cert and not _is_own_lab_org(cert):
        cert.role = "customer"
        cert.org_type = "certification_body"

    has_customer = any(
        o.role == "customer" and o.name and not _is_non_customer_org(o) for o in result
    )
    if has_customer:
        return result

    # Fallback: производитель = заказчик только если нет ОС
    manufacturer = next(
        (o for o in result if o.role == "manufacturer"),
        next((o for o in result if o.org_type == "manufacturer"), None),
    )
    if not manufacturer or _is_own_lab_org(manufacturer):
        return result

    customer = manufacturer.model_copy(deep=True)
    customer.role = "customer"
    mfg_key = normalize_org_name(manufacturer.name)
    if not any(
        normalize_org_name(o.name) == mfg_key and o.role == "customer" for o in result
    ):
        result.append(customer)

    return result


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

    org_type = _infer_header_org_type(text, name)
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


def extract_periodic_factory_address(text: str) -> str | None:
    """Адрес завода с бланка периодики (OCR / профиль).

    Не срабатывает на любом документе, где встречается «кабельный завод»
    (напр. направление с Тольяттинским КЗ).
    """
    if not text or not str(text).strip():
        return None
    head = text[:2500]

    # Чужой завод в шапке/теле без признаков Калуги → не подставлять профиль.
    if _OTHER_CABLE_PLANT_HINT.search(head) and not _source_looks_like_periodic_factory_letter(head):
        return None
    if not _source_looks_like_periodic_factory_letter(head):
        # Слабый OCR: только «кабельн…завод» без индекса/Калуги — недостаточно.
        return None

    if _PERIODIC_FACTORY_POSTAL:
        block = _PERIODIC_FACTORY_ADDRESS_BLOCK.search(head)
        if block:
            raw = f"{_PERIODIC_FACTORY_POSTAL}, {block.group(1)}"
            cleaned = sanitize_address(raw)
            if cleaned and not _looks_like_cable_marks(cleaned):
                return cleaned
        postal = re.search(rf"\b{re.escape(_PERIODIC_FACTORY_POSTAL)}\b", head)
        if postal:
            chunk = text[postal.start() : postal.start() + 180]
            cleaned = sanitize_address(chunk)
            if cleaned and not _looks_like_cable_marks(cleaned):
                return cleaned

    # Канон только при сильных признаках (уже проверены выше).
    return _PERIODIC_FACTORY_CANONICAL_ADDRESS or None


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

    is_direction = is_direction_document(text)
    is_act = is_act_document(text)

    header_org = _build_org_from_header(text)
    if header_org:
        if (is_direction or is_act) and header_org.org_type == "certification_body":
            header_org.role = "unknown"
            add(header_org, "unknown")
        elif is_direction and _is_non_customer_org(header_org):
            header_org.role = "unknown"
            add(header_org, "unknown")
        else:
            add(header_org, "customer")

    if is_act:
        app_name, app_addr = extract_applicant_details(text)
        if app_name:
            applicant = OrganizationExtract(
                name=app_name,
                address=app_addr,
                legal_address=app_addr,
                actual_address=app_addr,
                postal_code=_postal_from_address(app_addr),
                org_type="manufacturer",
                role="customer",
                confidence=0.85 if app_addr else 0.75,
            )
            add(applicant, "customer")

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

    if is_direction:
        cert_body = extract_certification_body_from_direction(text)
        if cert_body:
            # приоритет: ОС — заказчик; не затирать role=customer
            add(cert_body, "customer")
        testing_center = extract_testing_center_from_direction(text)
        if testing_center:
            add(testing_center, "unknown")

    found = finalize_organizations(found, text)
    found = assign_organization_roles(found, text)
    return enhance_organizations(text, found)


def pick_customer_name(organizations: list[OrganizationExtract]) -> str:
    for org in organizations:
        if org.role == "customer" and org.name and not _is_non_customer_org(org):
            return org.name
    # ОС с role unknown (до assign) — тоже кандидат в заказчики направления
    for org in organizations:
        if (
            org.org_type == "certification_body"
            and org.name
            and not _is_own_lab_org(org)
        ):
            return org.name
    for org in organizations:
        if org.role == "manufacturer" and org.name and not _is_own_lab_org(org):
            return org.name
    for org in organizations:
        if org.role == "unknown" and org.name and not _is_non_customer_org(org):
            return org.name
    return ""


# Папки пути, которые не бывают именем заказчика (prod path-hint, 27.07)
_PATH_SKIP_PARTS = re.compile(
    r"^(?:"
    r"\d{4}"
    r"|users?(?:_folder\$)?"
    r"|user_data"
    r"|temp|tmp|inbox|downloads?"
    r"|request_processor"
    r"|обработка\s+заявок"
    r"|расчёты\s+для\s+заказчиков"
    r"|расчеты\s+для\s+заказчиков"
    r"|документы?"
    r"|data|generated|extracted"
    r")$",
    re.IGNORECASE,
)
_PATH_MARK_LIKE = re.compile(
    r"(?:\d+\s*[xх×]\s*\d)|(?:нг\s*\()|(?:^лпмф)|(?:^ввг)|(?:^кв[вг])",
    re.IGNORECASE,
)
_PATH_ORG_HINT = re.compile(
    r"(?:ооо|ано|оао|зао|пао|ип\b|llc|ltd|jsc|inc\b)",
    re.IGNORECASE,
)


def suggest_customer_from_source_path(source_path: str | Path | None) -> str:
    """
    Эвристика заказчика из родительских папок пути файла.

    Не коммитит в БД — только подсказка для поля «Заказчик» (HITL).
    Примеры prod: …\\SUPR\\2026\\….pdf → «SUPR»;
    …\\АНО … Электросерт\\2026\\ЛПМФм\\….docx → «АНО … Электросерт».
    """
    if not source_path:
        return ""
    try:
        parts = list(Path(source_path).resolve().parts)
    except (OSError, RuntimeError, ValueError):
        parts = list(Path(str(source_path)).parts)
    if len(parts) < 2:
        return ""

    # Без имени файла; от ближайшей папки к корню
    candidates: list[str] = []
    for part in reversed(parts[:-1]):
        name = (part or "").strip().rstrip("\\/")
        if not name or name in (".", "..") or len(name) < 2:
            continue
        if name.endswith(":") or name.startswith("\\\\"):
            continue
        if _PATH_SKIP_PARTS.match(name):
            continue
        if name.endswith("$"):
            continue
        if _PATH_MARK_LIKE.search(name) and not _PATH_ORG_HINT.search(name):
            continue
        candidates.append(name)

    if not candidates:
        return ""

    # Предпочтение: юр. форма / «орган…» / «сертифик…»
    for name in candidates:
        if _PATH_ORG_HINT.search(name) or re.search(
            r"сертифик|завод|кабел", name, re.I
        ):
            return name
    # Короткий латинский код папки (SUPR)
    for name in candidates:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,15}", name):
            return name
    return candidates[0]


def pick_manufacturer_name(organizations: list[OrganizationExtract]) -> str:
    for org in organizations:
        if org.role == "manufacturer" and org.name and not _is_own_lab_org(org):
            return org.name
    for org in organizations:
        if org.org_type == "manufacturer" and org.name and not _is_own_lab_org(org):
            return org.name
    # Не подставлять ОС/ИЛ как производителя «по умолчанию»
    return ""