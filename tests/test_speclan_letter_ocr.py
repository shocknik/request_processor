"""Регрессия: СПЕЦЛАН в письмах после латинского OCR (CMELVIAH)."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import find_cable_marks

from tests.ocr_cache_helper import resolve_ocr_cache


def test_letter_145_ocr_cache_yields_speclan_marks() -> None:
    text = resolve_ocr_cache("145", "02.02.2026").read_text(encoding="utf-8")
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) >= 2
    joined = " ".join(marks).lower()
    assert "спецлан" in joined
    assert "cat 5" in joined
    assert "2x2x0,52" in joined.replace(" ", "")
    assert "4x2x0,52" in joined.replace(" ", "")