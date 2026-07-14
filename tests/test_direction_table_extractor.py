"""Тесты table-first extractor для направлений в ИЛ."""

from __future__ import annotations

import pytest

from request_processor.extraction.direction_table_extractor import (
    extract_marks_from_direction_table,
    extract_marks_from_tables,
    is_direction_table,
)
from request_processor.models import PdfExtractionResult
from request_processor.extraction.pdf_extractor import _resolve_cable_marks
from tests.fixture_loader import load_extraction_fixture


@pytest.fixture
def direction_fixture() -> PdfExtractionResult:
    return load_extraction_fixture("direction_sample.json")


def test_is_direction_table(direction_fixture: PdfExtractionResult) -> None:
    assert is_direction_table(direction_fixture.tables[0])


def test_extract_three_marks_with_tu(direction_fixture: PdfExtractionResult) -> None:
    table = direction_fixture.tables[0]
    marks = extract_marks_from_direction_table(table)

    assert len(marks) == 3
    assert all(m.document and "ТУ 16.К03-54-2011" in m.document for m in marks)


def test_requirements_raw_solar_radiation(direction_fixture: PdfExtractionResult) -> None:
    marks = extract_marks_from_tables(direction_fixture.tables)
    assert all(m.requirements_raw and "солнечного" in m.requirements_raw.lower() for m in marks)


def test_resolve_prefers_table_over_text(direction_fixture: PdfExtractionResult) -> None:
    marks = _resolve_cable_marks(direction_fixture.text, direction_fixture.tables)
    assert len(marks) == 3
    assert all(m.requirements_raw for m in marks)
    third = next(m for m in marks if "ПвП" in m.mark or "2х2х0,35" in m.mark)
    assert third.document and "ТУ 16.К03-54-2011" in third.document