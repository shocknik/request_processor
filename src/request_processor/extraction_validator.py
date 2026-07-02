"""
Оценка уверенности результата парсинга заявки (без ИИ).

Используется перед подтверждением оператором (human-in-the-loop).
См. Obsidian: «22 — Валидация парсинга (панель подтверждения)».
"""

from __future__ import annotations

import re

from .letter_extractor import is_business_letter, parse_business_letter
from .cable_mark_parser import mark_validation_from_match
from .models import (
    CableMarkMatch,
    DocumentType,
    FieldStatus,
    MarkValidation,
    OrgValidation,
    OrganizationExtract,
    PdfExtractionResult,
    ValidationReport,
)
from .pdf_extractor import is_plausible_mark

_TESTING_CENTER_HINTS = re.compile(
    r"кабель[\s\-–]*тест|испытательн\w*\s+(?:центр|лаборатор)|видяев|"
    r"ниц\s*[«\"]\s*кабель",
    re.IGNORECASE,
)

_MIN_TEXT_FOR_EMPTY_MARKS = 500
_LONG_ORG_NAME = 80
_OCR_CONFIDENCE_FACTOR = 0.85
_MISSING_TU_PENALTY = 0.10
_DUPLICATE_MARK_PENALTY = 0.05
_UNKNOWN_DOC_PENALTY = 0.10
_NO_INN_LETTER_PENALTY = 0.15


def detect_document_type(text: str) -> DocumentType:
    """Классифицирует тип входящего документа по тексту."""
    if not text or len(text) < 40:
        return "unknown"
    if is_business_letter(text):
        return "letter"
    head = text[:3000]
    if re.search(r"Генеральному|Уважаем\w+", head, re.IGNORECASE) and re.search(
        r"Просим\s+.*провести", head, re.IGNORECASE
    ):
        return "letter"
    if re.search(r"НАПРАВЛЕНИЕ", text, re.IGNORECASE) and re.search(
        r"испытательн", text, re.IGNORECASE
    ):
        return "direction"
    if re.search(r"Акт\s+отбора|отбор\s+образцов", text, re.IGNORECASE):
        return "act"
    return "unknown"


def _normalize_mark_key(mark: str) -> str:
    return re.sub(r"\s+", " ", mark.strip().lower())


def _is_testing_center_name(name: str) -> bool:
    return bool(_TESTING_CENTER_HINTS.search(name))


def _validate_mark(
    match: CableMarkMatch,
    *,
    ocr_used: bool,
    seen_keys: set[str],
) -> MarkValidation:
    confidence = 0.90 if not ocr_used else 0.75
    status = FieldStatus.ok
    warnings: list[str] = []

    if ocr_used:
        warnings.append("P1-1: OCR — проверьте марку вручную")
        confidence *= _OCR_CONFIDENCE_FACTOR

    if not is_plausible_mark(match.mark):
        status = FieldStatus.error
        confidence = min(confidence, 0.40)
        warnings.append("P1-2: марка не проходит проверку формата")

    if not match.document:
        if status == FieldStatus.ok:
            status = FieldStatus.warning
        confidence = max(0.0, confidence - _MISSING_TU_PENALTY)
        warnings.append("P1-3: ТУ/ГОСТ не извлечён")

    key = _normalize_mark_key(match.mark)
    if key in seen_keys:
        if status == FieldStatus.ok:
            status = FieldStatus.warning
        confidence = max(0.0, confidence - _DUPLICATE_MARK_PENALTY)
        warnings.append("P2-1: возможный дубликат марки")
    seen_keys.add(key)

    confidence = round(min(max(confidence, 0.0), 1.0), 2)
    return mark_validation_from_match(
        match,
        confidence=confidence,
        status=status,
        warnings=warnings,
        accepted=status != FieldStatus.error,
    )


def _validate_org(
    org: OrganizationExtract,
    *,
    document_type: DocumentType,
) -> OrgValidation:
    confidence = round(min(max(org.confidence, 0.0), 1.0), 2)
    status = FieldStatus.ok
    warnings: list[str] = []
    read_only = org.org_type == "testing_center" or (
        org.role not in ("customer", "manufacturer") and _is_testing_center_name(org.name)
    )

    if len(org.name) > _LONG_ORG_NAME:
        status = FieldStatus.error
        confidence = min(confidence, 0.30)
        warnings.append("P0-3: слишком длинное название (вероятна OCR-склейка)")

    if org.role == "customer" and _is_testing_center_name(org.name):
        status = FieldStatus.error
        confidence = min(confidence, 0.20)
        warnings.append("P0-1: заказчик похож на испытательный центр")

    if confidence < 0.60 and status == FieldStatus.ok:
        status = FieldStatus.warning
        warnings.append("P1-4: низкая уверенность парсера организации")

    if document_type == "letter" and org.role == "customer" and not org.inn:
        if status == FieldStatus.ok:
            status = FieldStatus.warning
        confidence = max(0.0, confidence - _NO_INN_LETTER_PENALTY)
        warnings.append("P1-5: у заказчика в письме не найден ИНН")

    return OrgValidation(
        role=org.role,
        name=org.name,
        inn=org.inn,
        address=org.address or org.legal_address,
        confidence=confidence,
        status=status,
        warnings=warnings,
        read_only=read_only,
    )


def _recipient_from_letter(text: str) -> str | None:
    parsed = parse_business_letter(text)
    if parsed and parsed.recipient_org_name:
        return parsed.recipient_org_name
    return None


def _worst_status(statuses: list[FieldStatus]) -> FieldStatus:
    if FieldStatus.error in statuses:
        return FieldStatus.error
    if FieldStatus.warning in statuses:
        return FieldStatus.warning
    return FieldStatus.ok


def _finalize_report(
    report: ValidationReport,
    *,
    text: str,
    ocr_used: bool,
) -> ValidationReport:
    flags: list[str] = []
    block_confirm = False

    if ocr_used:
        flags.append("P1-1: OCR — проверьте марки вручную")

    if report.document_type == "unknown":
        flags.append("P2-2: тип документа не определён")

    if not report.marks and len(text) > _MIN_TEXT_FOR_EMPTY_MARKS:
        flags.append("P0-2: марки не найдены в непустом документе")
        block_confirm = True

    customer_org = next((o for o in report.organizations if o.role == "customer"), None)
    if report.customer_name and _is_testing_center_name(report.customer_name):
        flags.append("P0-1: заказчик совпадает с испытательным центром")
        block_confirm = True
    elif customer_org and customer_org.status == FieldStatus.error:
        for warning in customer_org.warnings:
            if warning.startswith("P0-"):
                flags.append(warning)
                block_confirm = True

    if report.customer_name and len(report.customer_name) > _LONG_ORG_NAME:
        flags.append("P0-3: слишком длинное имя заказчика")
        block_confirm = True

    mark_statuses = [m.status for m in report.marks if m.accepted]
    org_statuses = [o.status for o in report.organizations if o.role in ("customer", "manufacturer")]
    overall_status = _worst_status(mark_statuses + org_statuses)

    scores: list[float] = [m.confidence for m in report.marks if m.accepted]
    if customer_org:
        scores.append(customer_org.confidence)
    elif report.customer_name:
        scores.append(0.5)
    overall_confidence = round(sum(scores) / len(scores), 2) if scores else 0.0

    if report.document_type == "unknown" and overall_status == FieldStatus.ok:
        overall_status = FieldStatus.warning
        overall_confidence = max(0.0, overall_confidence - _UNKNOWN_DOC_PENALTY)

    return report.model_copy(
        update={
            "flags": flags,
            "block_confirm": block_confirm,
            "overall_status": overall_status,
            "overall_confidence": overall_confidence,
        }
    )


def validate_extraction(result: PdfExtractionResult) -> ValidationReport:
    """
    Строит отчёт валидации по результату extract_from_document().

    Правила P0–P2 без ИИ. Не изменяет исходный result.
    """
    document_type = detect_document_type(result.text)
    seen_mark_keys: set[str] = set()

    marks = [
        _validate_mark(m, ocr_used=result.ocr_used, seen_keys=seen_mark_keys)
        for m in result.cable_marks
    ]
    organizations = [
        _validate_org(org, document_type=document_type) for org in result.organizations
    ]

    recipient_name = _recipient_from_letter(result.text) if document_type == "letter" else None

    draft = ValidationReport(
        document_type=document_type,
        marks=marks,
        organizations=organizations,
        customer_name=result.customer_name,
        manufacturer_name=result.manufacturer_name,
        recipient_name=recipient_name,
    )
    return _finalize_report(draft, text=result.text, ocr_used=result.ocr_used)


def apply_operator_edits(
    report: ValidationReport,
    *,
    marks: list[MarkValidation] | None = None,
    customer_name: str | None = None,
    manufacturer_name: str | None = None,
    text: str = "",
    ocr_used: bool = False,
) -> ValidationReport:
    """
    Применяет правки оператора и пересчитывает статусы подтверждения.

    text и ocr_used нужны для повторной проверки P0-2 и OCR-флагов.
    """
    updated = report.model_copy(deep=True)
    if marks is not None:
        updated.marks = marks
    if customer_name is not None:
        updated.customer_name = customer_name.strip()
    if manufacturer_name is not None:
        updated.manufacturer_name = manufacturer_name.strip()

    if customer_name is not None:
        customer_org = next((o for o in updated.organizations if o.role == "customer"), None)
        if customer_org:
            orgs = list(updated.organizations)
            idx = orgs.index(customer_org)
            orgs[idx] = customer_org.model_copy(
                update={"name": updated.customer_name, "status": FieldStatus.ok, "warnings": []}
            )
            if len(updated.customer_name) <= _LONG_ORG_NAME and not _is_testing_center_name(
                updated.customer_name
            ):
                orgs[idx] = orgs[idx].model_copy(update={"confidence": max(customer_org.confidence, 0.75)})
            else:
                orgs[idx] = _validate_org(
                    OrganizationExtract(
                        name=updated.customer_name,
                        role="customer",
                        confidence=customer_org.confidence,
                        inn=customer_org.inn,
                        address=customer_org.address,
                        org_type="manufacturer",
                    ),
                    document_type=updated.document_type,
                )
            updated.organizations = orgs

    return _finalize_report(updated, text=text, ocr_used=ocr_used)


def format_validation_report(report: ValidationReport, *, source_name: str = "") -> str:
    """Текстовое представление отчёта для CLI и логов."""
    header = source_name or "документ"
    status_icon = {"ok": "OK", "warning": "WARNING", "error": "ERROR"}[report.overall_status.value]
    lines = [
        f"Документ: {header}",
        f"Тип: {report.document_type} · уверенность: {report.overall_confidence:.0%} · "
        f"статус: {status_icon}",
    ]
    if report.recipient_name:
        lines.append(f"Получатель (ИЛ): {report.recipient_name}")
    if report.block_confirm:
        lines.append("Подтверждение заблокировано до исправления критичных полей.")

    lines.append(f"Марки ({len(report.marks)}):")
    for mark in report.marks:
        icon = {"ok": "[✓]", "warning": "[⚠]", "error": "[✗]"}[mark.status.value]
        accepted = " " if mark.accepted else " (снята)"
        tu = f"  {mark.document}" if mark.document else ""
        lines.append(f"  {icon} {mark.confidence:.0%}  {mark.mark}{tu}{accepted}")

    if report.organizations:
        lines.append("Организации:")
        for org in report.organizations:
            icon = {"ok": "[✓]", "warning": "[⚠]", "error": "[✗]"}[org.status.value]
            inn = f"  ИНН {org.inn}" if org.inn else ""
            lines.append(f"  {icon} {org.confidence:.0%}  {org.role}  {org.name}{inn}")

    if report.flags:
        lines.append("Флаги:")
        for flag in report.flags:
            lines.append(f"  - {flag}")

    return "\n".join(lines)