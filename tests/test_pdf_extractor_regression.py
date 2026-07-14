"""Регрессия extract_from_pdf после table-first (search_text)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from request_processor.models import PdfExtractionResult
from request_processor.extraction.pdf_extractor import extract_from_document
from tests.fixture_loader import load_extraction_fixture


@pytest.fixture
def direction_result() -> PdfExtractionResult:
    return load_extraction_fixture("direction_sample.json")


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
                with patch(
                    "request_processor.extraction.pdf_extractor._pdf_page_stats",
                    return_value=(direction_result.page_count, False, direction_result.text),
                ):
                    result = extract_from_document(pdf, use_ocr=False)

    assert len(result.cable_marks) == 3
    assert result.organizations
    assert all(m.requirements_raw for m in result.cable_marks)