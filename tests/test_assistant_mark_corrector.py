"""Тесты ИИ-ассистента: коррекция марок (детерминированный слой)."""

from __future__ import annotations

from request_processor.assistant import MarkSuggestion, suggest_mark_correction


def test_kcbur_corrected_to_ksbng() -> None:
    result = suggest_mark_correction("KCBur(A)-LS 3x2,50")
    assert isinstance(result, MarkSuggestion)
    assert result.suggested.startswith("КСБнг(А)")
    assert result.changed


def test_cyrillic_mark_mostly_unchanged() -> None:
    raw = "ВВГ-Пнг(А) 3х2,5"
    result = suggest_mark_correction(raw)
    assert "ВВГ" in result.suggested
    # без сильного fuzzy-шума обозначение не должно «плыть»
    assert "3х2,5" in result.suggested or "3x2,5" in result.suggested