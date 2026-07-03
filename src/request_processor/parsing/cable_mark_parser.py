"""
Парсер марок кабелей и извлечение ТУ/ГОСТ из контекста.

ТУ с кириллической буквой в номере (16.К99-058-2014) — отдельный шаблон _TU_PATTERN.
OCR-правки: fix_ocr_document_text() (Ty→ТУ, K→К).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from ..models import CableMark, CableMarkMatch, CableMarkRecord, FieldStatus, MarkValidation

_FIRE_PATTERNS = [
    r"нг\(А\)-LSLTx",
    r"нг\(А\)-LS",
    r"нг\(А\)",
    r"нг\([^)]+\)",
    r"HF",
    r"FRHF",
    r"FRLS",
    r"-LS\b",
]

# ТУ 16.К99-058-2014 — после точки идёт кириллическая «К»
_TU_PATTERN = re.compile(
    r"(?:ТУ|TU|Ty)\s*\d+\.[КкKk]\d{2,3}-\d{3}-\d{4}",
    re.IGNORECASE,
)
_GOST_STO_PATTERN = re.compile(
    r"(?:ГОСТ|СТО|Р\s*МЭК)\s*[\d\.\-/]+(?:\s*[\d\-/]+)*",
    re.IGNORECASE,
)
_DOC_PATTERN = re.compile(
    r"(?:ТУ|TU|Ty|ГОСТ|СТО|Р\s*МЭК)\s*[\d\.\-/A-Za-zА-Яа-яЁё]+(?:-[\dA-Za-zА-Яа-яЁё]+)*",
    re.IGNORECASE,
)


def _detect_fire_class(mark: str) -> str | None:
    for pattern in _FIRE_PATTERNS:
        if match := re.search(pattern, mark, re.IGNORECASE):
            return match.group(0)
    return None


def extract_base_brand(mark: str) -> str:
    """Буквенная часть марки без пожарного обозначения (ВВГ-П из ВВГ-Пнг(А))."""
    name = re.split(r"\s+\d", mark, maxsplit=1)[0].strip()
    for pattern in _FIRE_PATTERNS:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    return name.rstrip("-").strip() or mark.split()[0]


def _extract_numbers(mark: str) -> dict[str, Any]:
    s = mark.replace("×", "х").replace("x", "х").replace("X", "х").replace(",", ".")
    result: dict[str, Any] = {
        "cores": 1,
        "groups": 1,
        "size": 1.0,
        "structural_element_type": "жила",
        "structural_elements_count": 1,
        "size_unit": "mm2",
    }

    if m := re.search(r"(\d+)\s*[зЗ]\s*х\s*(\d+)\s*х\s*([\d.]+)", s):
        groups = int(m.group(1))
        per_group = int(m.group(2))
        size = float(m.group(3))
        result.update(
            {
                "groups": groups,
                "cores": groups * per_group,
                "size": size,
                "structural_element_type": "тройка" if per_group == 3 else "пара",
                "structural_elements_count": groups,
            }
        )
        return result

    if m := re.search(r"(\d+)\s*х\s*\(\s*(\d+)\s*х\s*([\d.]+)\s*\)", s):
        groups = int(m.group(1))
        per_group = int(m.group(2))
        size = float(m.group(3))
        result.update(
            {
                "groups": groups,
                "cores": groups * per_group,
                "size": size,
                "structural_element_type": "пара",
                "structural_elements_count": groups,
            }
        )
        return result

    if m := re.search(r"(\d+)\s*х\s*(\d+)\s*х\s*([\d.]+)", s):
        groups = int(m.group(1))
        per_group = int(m.group(2))
        size = float(m.group(3))
        result.update(
            {
                "groups": groups,
                "cores": groups * per_group,
                "size": size,
                "structural_element_type": "пара",
                "structural_elements_count": groups,
                "is_lan": True,
                "size_unit": "mm",
            }
        )
        return result

    if m := re.search(r"(\d+)\s*[зЗ]?\s*х\s*([\d.]+)", s):
        cores = int(m.group(1))
        size = float(m.group(2))
        result.update(
            {
                "cores": cores,
                "groups": 1,
                "size": size,
                "structural_element_type": "жила",
                "structural_elements_count": cores,
            }
        )
        return result

    return result


def fix_ocr_document_text(text: str) -> str:
    """Правит типичные OCR-ошибки в обозначениях ТУ/ГОСТ."""
    text = re.sub(r"\bTy\s+", "ТУ ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bTU\s+", "ТУ ", text, flags=re.IGNORECASE)
    text = re.sub(r"(ТУ\s*\d+\.)K(\d)", r"\1К\2", text, flags=re.IGNORECASE)
    return text


def extract_document_from_text(text: str | None) -> str | None:
    """Извлекает ТУ/ГОСТ из фрагмента текста (марка + хвост строки)."""
    if not text:
        return None
    blob = fix_ocr_document_text(text)

    tu = _TU_PATTERN.search(blob)
    if tu:
        return re.sub(r"\s+", " ", tu.group(0)).strip()

    for pattern in (_GOST_STO_PATTERN, _DOC_PATTERN):
        m = pattern.search(blob)
        if m:
            doc = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(doc) > 6 and not re.fullmatch(r"ТУ\s*\d+\.?", doc, re.I):
                return doc
    return None


def extract_document_from_context(context: str | None) -> str | None:
    """Извлекает ТУ/ГОСТ из контекста вокруг марки в PDF/письме."""
    return extract_document_from_text(context)


def parse_cable_mark(mark: str) -> CableMark:
    if not mark or not mark.strip():
        raise ValueError("Пустая марка")

    original = mark.strip()
    brand = extract_base_brand(original)
    fire = _detect_fire_class(original)
    nums = _extract_numbers(original)

    material = None
    if m := re.search(r"\(([^)]+)\)", original):
        material = m.group(1)

    voltage = None
    if m := re.search(r"[-–]?\s*(\d[.,]?\d*)\s*(кВ)?", original):
        try:
            voltage = float(m.group(1).replace(",", "."))
            if voltage > 100:
                voltage /= 1000
        except ValueError:
            pass

    has_armor = bool(re.search(r"[ВвБб][Бб]", original) or "брон" in original.lower())

    return CableMark(
        full_mark=original,
        brand=brand,
        fire_class=fire,
        cores=nums["cores"],
        groups=nums["groups"],
        size=nums["size"],
        material=material,
        voltage=voltage,
        has_armor=has_armor,
        is_lan=nums.get("is_lan", False),
        extras={"raw": original},
    )


def mark_validation_from_match(
    match: CableMarkMatch,
    *,
    confidence: float = 0.9,
    status: FieldStatus = FieldStatus.ok,
    warnings: list[str] | None = None,
    accepted: bool = True,
) -> MarkValidation:
    """Строит MarkValidation со всеми полями для cable_marks из найденной марки."""
    record = parse_cable_mark_record(
        match.mark,
        document=match.document,
        context=match.context,
    )
    return MarkValidation(
        mark=record.full_mark,
        document=record.document,
        context=match.context,
        requirements_raw=match.requirements_raw,
        brand=record.brand,
        fire_class=record.fire_class,
        cores_count=record.cores_count,
        structural_element_type=record.structural_element_type,
        structural_elements_count=record.structural_elements_count,
        characteristic_size=record.characteristic_size,
        size_unit=record.size_unit,
        confidence=confidence,
        status=status,
        warnings=warnings or [],
        accepted=accepted,
    )


def parse_cable_mark_record(
    full_mark: str,
    *,
    document: str | None = None,
    context: str | None = None,
) -> CableMarkRecord:
    """Разбирает марку в запись для накопительной таблицы cable_marks."""
    parsed = parse_cable_mark(full_mark)
    nums = _extract_numbers(full_mark)
    doc = document or extract_document_from_context(context)

    size_unit: Literal["mm2", "mm"] = nums.get("size_unit", "mm2")
    if nums.get("is_lan"):
        size_unit = "mm"

    return CableMarkRecord(
        full_mark=parsed.full_mark,
        brand=parsed.brand,
        fire_class=parsed.fire_class,
        cores_count=parsed.cores,
        structural_element_type=nums["structural_element_type"],
        structural_elements_count=nums["structural_elements_count"],
        characteristic_size=parsed.size,
        size_unit=size_unit,
        document=doc,
    )