"""Марки направлений СЕРК: КГ* и VicabFLEX."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import find_cable_marks


def test_kg_star_core_marks_from_direction_text() -> None:
    text = (
        "КГРвЭСТ 3*35+16/3в+3*2,5 - 1140 ГОСТ 31945-2012 "
        "КГТЭСТу 3*16+1*10+1*16 - 1140"
    )
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) == 2
    assert any("КГРвЭСТ" in m and "3*35" in m for m in marks)
    assert any("КГТЭСТу" in m and "3*16" in m for m in marks)


def test_vicabflex_mark_clean_text() -> None:
    text = (
        "VicabFLEX 110 CY нг(A)-LS 24x0.5 300/500 В "
        "VicabFLEX 115 CY 0,6/1 кВ 3х95 600/1000В"
    )
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) == 2
    assert any("110" in m and "24x0.5" in m for m in marks)
    assert any("115" in m and "3х95" in m or "3x95" in m for m in marks)


def test_vicabflex_ocr_garbled_text() -> None:
    text = "Мархн VисабFLЕХ 115 СУ 0,6/1 КБ 3х95 600/1000 Б"
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) >= 1
    assert "VicabFLEX" in marks[0]
    assert "3х95" in marks[0] or "3x95" in marks[0]