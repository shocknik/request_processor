"""Загрузка эталонных JSON для регрессионных тестов."""

from __future__ import annotations

import json
from pathlib import Path

from request_processor.extraction.pdf_extractor import build_search_text
from request_processor.models import PdfExtractionResult

EXTRACTED_DIR = Path(__file__).resolve().parents[1] / "data" / "extracted"


def load_extraction_fixture(name: str) -> PdfExtractionResult:
    path = EXTRACTED_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    return PdfExtractionResult.model_validate(data)


def fixture_search_text(result: PdfExtractionResult) -> str:
    return build_search_text(result.text, result.tables)