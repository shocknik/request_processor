"""Общие фикстуры pytest для эталонных JSON в data/extracted/."""

from __future__ import annotations

import pytest

from request_processor.models import PdfExtractionResult

from tests.fixture_loader import load_extraction_fixture


@pytest.fixture
def letter_kaluga() -> PdfExtractionResult:
    return load_extraction_fixture("Письмо на период. исп. от 04.05.26.json")


@pytest.fixture
def letter_145() -> PdfExtractionResult:
    return load_extraction_fixture("Письмо 145 от 02.02.2026 .json")


@pytest.fixture
def direction_il() -> PdfExtractionResult:
    return load_extraction_fixture("27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json")


@pytest.fixture
def act_sampling() -> PdfExtractionResult:
    return load_extraction_fixture("27_1-2-2026 Акт отбора 10094807(1).json")