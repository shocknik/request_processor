"""Регрессия: СПЕЦЛАН в письмах после латинского OCR (CMELVIAH)."""

from __future__ import annotations

from pathlib import Path

from request_processor.extraction.pdf_extractor import find_cable_marks

_OCR_CACHE = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "ocr_cache"
    / "Письмо_145_от_02.02.2026__dfe806596d303038e3d335a5_dpi200_tesseract.txt"
)


def test_letter_145_ocr_cache_yields_speclan_marks() -> None:
    text = _OCR_CACHE.read_text(encoding="utf-8")
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) >= 2
    joined = " ".join(marks).lower()
    assert "спецлан" in joined
    assert "cat 5" in joined
    assert "2x2x0,52" in joined.replace(" ", "")
    assert "4x2x0,52" in joined.replace(" ", "")