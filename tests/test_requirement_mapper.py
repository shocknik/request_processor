"""Тесты маппинга требований → испытания (PR-2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from request_processor.extraction_validator import validate_extraction
from request_processor.models import CableMarkMatch, PdfExtractionResult
from request_processor.requirement_mapper import (
    map_requirements_to_tests,
    suggest_tests_for_mark,
)
from request_processor.pdf_extractor import _resolve_cable_marks
from request_processor.sqlite_repo import add_test_mapping, init_db

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "extracted" / (
    "27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json"
)


@pytest.fixture
def direction_result() -> PdfExtractionResult:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return PdfExtractionResult.model_validate(data)


def test_solar_radiation_from_direction_requirements(
    direction_result: PdfExtractionResult,
) -> None:
    mark = _resolve_cable_marks(direction_result.text, direction_result.tables)[0]
    assert mark.requirements_raw
    suggestions = map_requirements_to_tests(mark.requirements_raw)
    codes = [s.code for s in suggestions]
    assert "solar_radiation" in codes
    solar = next(s for s in suggestions if s.code == "solar_radiation")
    assert solar.confidence >= 0.85
    assert solar.source == "builtin"


def test_suggest_tests_for_mark(direction_result: PdfExtractionResult) -> None:
    mark = _resolve_cable_marks(direction_result.text, direction_result.tables)[0]
    suggestions = suggest_tests_for_mark(mark)
    assert any(s.code == "solar_radiation" for s in suggestions)


def test_validation_report_includes_suggested_tests(
    direction_result: PdfExtractionResult,
) -> None:
    from request_processor.pdf_extractor import _resolve_cable_marks

    marks = _resolve_cable_marks(direction_result.text, direction_result.tables)
    result = direction_result.model_copy(update={"cable_marks": marks})
    report = validate_extraction(result)
    with_suggestions = [m for m in report.marks if m.suggested_tests]
    assert len(with_suggestions) == 3
    assert all("solar_radiation" in m.suggested_tests for m in with_suggestions)


def test_database_mapping(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    add_test_mapping("стойкость к ультрафиолету", "solar_radiation", db_path=db)
    suggestions = map_requirements_to_tests(
        "Проверить стойкость к ультрафиолету на образце",
        db_path=db,
    )
    codes = [s.code for s in suggestions]
    assert "solar_radiation" in codes
    db_hit = next(s for s in suggestions if s.code == "solar_radiation" and s.source == "database")
    assert db_hit.mapping_id is not None