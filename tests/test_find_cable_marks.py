"""Smoke-тесты find_cable_marks / table-first на эталонных JSON."""

from __future__ import annotations

import re

import pytest

from request_processor.extraction.pdf_extractor import _resolve_cable_marks, find_cable_marks
from request_processor.parsing.cable_mark_parser import _safe_float, parse_cable_mark

from tests.fixture_loader import EXTRACTED_DIR, load_extraction_fixture


def _normalize_mark(mark: str) -> str:
    text = mark.lower().replace("х", "x").replace("×", "x")
    return re.sub(r"\s+", "", text)


def _marks_from_result(result) -> list[str]:
    if result.tables:
        return [m.mark for m in _resolve_cable_marks(result.text, result.tables)]
    return [m.mark for m in find_cable_marks(result.text)]


@pytest.mark.parametrize(
    "fixture_name,min_count,required_fragments",
    [
        (
            "letter_periodic_sample.json",
            3,
            ("пвснг", "апув", "пбгвв"),
        ),
        (
            "letter_lan_sample.json",
            2,
            ("спецлан", "cat5"),
        ),
        (
            "direction_sample.json",
            3,
            ("рквнг", "пcпcнг", "пвпнг"),
        ),
        (
            "act_sample.json",
            17,
            ("ккзмк",),
        ),
    ],
)
def test_find_cable_marks_on_fixtures(
    fixture_name: str,
    min_count: int,
    required_fragments: tuple[str, ...],
) -> None:
    result = load_extraction_fixture(fixture_name)
    marks = _marks_from_result(result)
    normalized = [_normalize_mark(m) for m in marks]

    assert len(marks) >= min_count
    for fragment in required_fragments:
        assert any(fragment in mark for mark in normalized), (
            f"{fixture_name}: нет фрагмента {fragment!r} в {marks}"
        )


def test_letter_periodic_extracts_vvg_and_four_marks() -> None:
    """Письмо производителя: 4 марки из OCR-таблицы."""
    result = load_extraction_fixture("letter_periodic_sample.json")
    marks = [_normalize_mark(m) for m in _marks_from_result(result)]
    assert len(marks) >= 4
    joined = " ".join(marks)
    assert "ввг" in joined
    assert "пвснг" in joined
    assert "апув" in joined
    assert "пбгвв" in joined
    assert "3x4ок" in joined or "3х4ок" in joined


@pytest.mark.parametrize("sample", ["ВВГ-Пнг(А) 3х4ок(N,PE)-0,66", "АПуВ 1х6", "ККЗ МК РкВнг(А)-FRLSLTх-УФ 2зх2х1,0м-250"])
def test_find_cable_marks_inline_samples(sample: str) -> None:
    found = find_cable_marks(f"марки: {sample}")
    assert found
    assert _normalize_mark(sample) in _normalize_mark(found[0].mark)


def test_find_cable_marks_empty_text() -> None:
    assert find_cable_marks("") == []
    assert find_cable_marks("   \n  ") == []


def test_all_fixture_json_files_parseable() -> None:
    for path in sorted(EXTRACTED_DIR.glob("*.json")):
        result = load_extraction_fixture(path.name)
        marks = _marks_from_result(result)
        assert isinstance(marks, list)


def test_safe_float_trailing_dot() -> None:
    assert _safe_float("1.5.") == 1.5
    assert _safe_float("2,5") == 2.5


def test_parse_cable_mark_lan_size_with_trailing_dot() -> None:
    parsed = parse_cable_mark("КМВЭВнг(А)-LS 1х2x1,5")
    assert parsed.size == 1.5
    assert parsed.groups == 1