"""Регрессия extract_from_pdf после table-first (search_text)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from request_processor.models import PdfExtractionResult
from request_processor.extraction.pdf_extractor import extract_from_document

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "extracted" / (
    "27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json"
)


@pytest.fixture
def direction_result() -> PdfExtractionResult:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return PdfExtractionResult.model_validate(data)


def test_extract_from_pdf_does_not_raise_search_text(
    tmp_path: Path,
    direction_result: PdfExtractionResult,
) -> None:
    pdf = tmp_path / "direction.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with patch(
        "request_processor.extraction.pdf_extractor.extract_text",
        return_value=direction_result.text,
    ):
        with patch(
            "request_processor.extraction.pdf_extractor.extract_tables",
            return_value=direction_result.tables,
        ):
            with patch(
                "request_processor.extraction.pdf_extractor._detect_scanned",
                return_value=(False, direction_result.page_count),
            ):
                result = extract_from_document(pdf, use_ocr=False)

    assert len(result.cable_marks) == 3
    assert result.organizations
    assert all(m.requirements_raw for m in result.cable_marks)