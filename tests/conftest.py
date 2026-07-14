"""Общие фикстуры pytest для эталонных JSON в data/extracted/."""

from __future__ import annotations

import pytest

from request_processor.models import PdfExtractionResult

from tests.fixture_loader import load_extraction_fixture


@pytest.fixture
def letter_periodic() -> PdfExtractionResult:
    return load_extraction_fixture("letter_periodic_sample.json")


@pytest.fixture
def letter_145() -> PdfExtractionResult:
    return load_extraction_fixture("letter_lan_sample.json")


@pytest.fixture
def direction_il() -> PdfExtractionResult:
    return load_extraction_fixture("direction_sample.json")


@pytest.fixture
def act_sampling() -> PdfExtractionResult:
    return load_extraction_fixture("act_sample.json")