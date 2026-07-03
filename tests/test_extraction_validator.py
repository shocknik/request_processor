"""Smoke-тесты extraction_validator на эталонных JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from request_processor.validation.extraction_validator import (
    apply_operator_edits,
    detect_document_type,
    format_validation_report,
    validate_extraction,
)
from request_processor.models import FieldStatus, PdfExtractionResult

EXTRACTED_DIR = Path(__file__).resolve().parents[1] / "data" / "extracted"


def _load_fixture(name: str) -> PdfExtractionResult:
    path = EXTRACTED_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    return PdfExtractionResult.model_validate(data)


def test_detect_document_type_letter() -> None:
    result = _load_fixture("Письмо на период. исп. от 04.05.26.json")
    assert detect_document_type(result.text) == "letter"


def test_detect_document_type_direction() -> None:
    result = _load_fixture("27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json")
    assert detect_document_type(result.text) == "direction"


def test_letter_kaluga_four_marks_with_ocr_warning() -> None:
    result = _load_fixture("Письмо на период. исп. от 04.05.26.json")
    report = validate_extraction(result)

    assert report.document_type == "letter"
    assert len(report.marks) == 4
    assert report.overall_status in (FieldStatus.warning, FieldStatus.ok)
    assert any("OCR" in f for f in report.flags)
    assert not report.block_confirm


def test_letter_145_extracts_lan_marks_with_ocr_warning() -> None:
    result = _load_fixture("Письмо 145 от 02.02.2026 .json")
    report = validate_extraction(result)

    assert report.document_type == "letter"
    assert len(report.marks) >= 2
    assert any("Cat 5" in m.mark for m in report.marks)
    assert not report.block_confirm
    assert any("P1-1" in f for f in report.flags)


def test_letter_145_customer_has_ocr_warning() -> None:
    result = _load_fixture("Письмо 145 от 02.02.2026 .json")
    report = validate_extraction(result)

    assert not report.block_confirm
    customer = next(o for o in report.organizations if o.role == "customer")
    assert customer.name and "Спецкабель" in customer.name
    assert customer.status in (FieldStatus.error, FieldStatus.warning, FieldStatus.ok)


def test_direction_three_marks_tu_warnings() -> None:
    result = _load_fixture("27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json")
    report = validate_extraction(result)

    assert report.document_type == "direction"
    assert len(report.marks) == 3
    assert not report.block_confirm
    assert any(m.status == FieldStatus.warning for m in report.marks)


def test_p0_customer_is_testing_center() -> None:
    from request_processor.models import OrganizationExtract, PdfExtractionResult

    result = PdfExtractionResult(
        source_path="test.pdf",
        page_count=1,
        text="Генеральному директору\nПросим провести\nмарки: ВВГ 3х2,5",
        cable_marks=[],
        organizations=[
            OrganizationExtract(
                name='ООО НИЦ «Кабель-Тест»',
                role="customer",
                org_type="testing_center",
                confidence=0.7,
            )
        ],
        customer_name='ООО НИЦ «Кабель-Тест»',
    )
    report = validate_extraction(result)
    assert report.block_confirm is True
    assert any("P0-1" in f for f in report.flags)


def test_apply_operator_edits_fixes_customer() -> None:
    result = _load_fixture("Письмо 145 от 02.02.2026 .json")
    report = validate_extraction(result)

    fixed = apply_operator_edits(
        report,
        customer_name='ООО НПП «Спецкабель»',
        text=result.text,
        ocr_used=result.ocr_used,
    )
    assert fixed.customer_name == 'ООО НПП «Спецкабель»'
    customer = next(o for o in fixed.organizations if o.role == "customer")
    assert customer.status == FieldStatus.ok
    assert not _is_testing_center_in_customer(fixed)
    assert not fixed.block_confirm


def _is_testing_center_in_customer(report) -> bool:
    return any("P0-1" in f for f in report.flags)


def test_format_validation_report_contains_marks() -> None:
    result = _load_fixture("Письмо на период. исп. от 04.05.26.json")
    report = validate_extraction(result)
    text = format_validation_report(report, source_name="test.pdf")
    assert "Марки (4)" in text
    assert "ВВГ" in text or "ПВС" in text


@pytest.mark.parametrize(
    "fixture,expected_type",
    [
        ("27_1-2-2026 Акт отбора 10094807(1).json", "act"),
    ],
)
def test_document_types(fixture: str, expected_type: str) -> None:
    result = _load_fixture(fixture)
    assert detect_document_type(result.text) == expected_type
    report = validate_extraction(result)
    assert report.document_type == expected_type
    assert len(report.marks) >= 10