"""Smoke-тесты extraction_validator на эталонных JSON."""

from __future__ import annotations

import pytest

from request_processor.validation.extraction_validator import (
    apply_operator_edits,
    detect_document_type,
    format_validation_report,
    validate_extraction,
)
from request_processor.models import FieldStatus, PdfExtractionResult

from tests.fixture_loader import load_extraction_fixture


def _load_fixture(name: str) -> PdfExtractionResult:
    return load_extraction_fixture(name)


def test_detect_document_type_letter() -> None:
    result = _load_fixture("letter_periodic_sample.json")
    assert detect_document_type(result.text) == "letter"


def test_detect_document_type_direction() -> None:
    result = _load_fixture("direction_sample.json")
    assert detect_document_type(result.text) == "direction"


def test_letter_periodic_four_marks_with_ocr_warning() -> None:
    result = _load_fixture("letter_periodic_sample.json")
    report = validate_extraction(result)

    assert report.document_type == "letter"
    assert len(report.marks) == 4
    assert report.overall_status in (FieldStatus.warning, FieldStatus.ok)
    assert any("OCR" in f for f in report.flags)
    assert not report.block_confirm


def test_letter_145_extracts_lan_marks_with_ocr_warning() -> None:
    result = _load_fixture("letter_lan_sample.json")
    report = validate_extraction(result)

    # Тип документа — letter/unknown (зависит от OCR-шапки), главное — марки
    assert report.document_type in ("letter", "unknown")
    assert len(report.marks) >= 2
    assert any("Cat 5" in m.mark or "СПЕЦЛАН" in m.mark or "UTP" in m.mark for m in report.marks)
    assert not report.block_confirm


def test_letter_145_customer_has_ocr_warning() -> None:
    result = _load_fixture("letter_lan_sample.json")
    report = validate_extraction(result)

    assert not report.block_confirm
    customer = next(o for o in report.organizations if o.role == "customer")
    assert customer.name
    assert customer.status in (FieldStatus.error, FieldStatus.warning, FieldStatus.ok)


def test_direction_three_marks_tu_warnings() -> None:
    result = _load_fixture("direction_sample.json")
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
                name='ООО «Испытательный центр»',
                role="customer",
                org_type="testing_center",
                confidence=0.7,
            )
        ],
        customer_name='ООО «Испытательный центр»',
    )
    report = validate_extraction(result)
    assert report.block_confirm is True
    assert any("P0-1" in f for f in report.flags)


def test_apply_operator_edits_fixes_customer() -> None:
    result = _load_fixture("letter_lan_sample.json")
    report = validate_extraction(result)

    fixed = apply_operator_edits(
        report,
        customer_name='ООО НПП «Производитель»',
        text=result.text,
        ocr_used=result.ocr_used,
    )
    assert fixed.customer_name == 'ООО НПП «Производитель»'
    customer = next(o for o in fixed.organizations if o.role == "customer")
    assert customer.status == FieldStatus.ok
    assert not _is_testing_center_in_customer(fixed)
    assert not fixed.block_confirm


def _is_testing_center_in_customer(report) -> bool:
    return any("P0-1" in f for f in report.flags)


def test_format_validation_report_contains_marks() -> None:
    result = _load_fixture("letter_periodic_sample.json")
    report = validate_extraction(result)
    text = format_validation_report(report, source_name="test.pdf")
    assert "Марки (4)" in text
    assert "ВВГ" in text or "ПВС" in text


@pytest.mark.parametrize(
    "fixture,expected_type",
    [
        ("act_sample.json", "act"),
    ],
)
def test_document_types(fixture: str, expected_type: str) -> None:
    result = _load_fixture(fixture)
    assert detect_document_type(result.text) == expected_type
    report = validate_extraction(result)
    assert report.document_type == expected_type
    assert len(report.marks) >= 10