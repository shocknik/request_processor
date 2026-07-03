"""Регрессия: письмо на периодические испытания (Калужский завод)."""

from __future__ import annotations

from pathlib import Path

from request_processor.extraction.pdf_extractor import find_cable_marks

_OCR = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "ocr_cache"
    / "Письмо_на_период._исп._от_04.05.26_c44b8cb8c746c58aaf21198b_dpi200_tesseract.txt"
)

_EXPECTED = (
    "ВВГнг(А) 3х4ок(N,PE)-0,66",
    "ПВСнг(А)-LS 3х2,50",
    "АПуВ 1х6",
    "ПБГВВ 2х1,5",
)


def test_kaluga_letter_four_marks_normalized() -> None:
    text = _OCR.read_text(encoding="utf-8")
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) == 4
    for expected in _EXPECTED:
        assert any(
            expected.replace(" ", "").lower() in m.replace(" ", "").lower() for m in marks
        ), f"нет {expected!r} в {marks}"


_GARBLED_TABLE = """периодические испытания
13х4ок (N, PE)-0,66    16470,00    13500,00    2970,00    40
2    ПВСнг(А)-LS 3х2,5064500,00400
3    АПуВ 1х6    35685,00    29250,00    6435,00    50
4    ПБГВВ 2х1,522500,0040"""


def test_kaluga_garbled_table_without_periodic_word() -> None:
    """Только строки таблицы — без заголовка «периодические испытания»."""
    table_only = _GARBLED_TABLE.split("\n", 1)[1]
    marks = [m.mark for m in find_cable_marks(table_only)]
    assert len(marks) == 4
    assert marks[0].startswith("ВВГнг(А)")


def test_kaluga_garbled_table_with_prices() -> None:
    """Таблица из GUI/OCR со склеенными ценами и номером строки «1»."""
    marks = [m.mark for m in find_cable_marks(_GARBLED_TABLE)]
    assert len(marks) == 4
    assert marks[0].startswith("ВВГнг(А)")
    assert "3х4ок" in marks[0].replace("x", "х")
    assert marks[1] == "ПВСнг(А)-LS 3х2,50"
    assert marks[2] == "АПуВ 1х6"
    assert marks[3] == "ПБГВВ 2х1,5"