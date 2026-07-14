"""Регрессия: письмо на периодические испытания (Кабельный завод)."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import find_cable_marks

_INLINE_OCR = """Nnepuoauyeckie UCNblITAHMA
Кабель силовой марки: ВВГнг(А) 3х4ок(N,PE)-0,66
ПВСнг(А)-LS 3х2,50
Провод марки АПуВ 1х6
Провод марки ПБГВВ 2х1,5"""

_EXPECTED = (
    "3х4ок",  # ВВГнг / ВВГ-Пнг — допустимы оба варианта нормализации
    "ПВСнг(А)-LS 3х2,50",
    "АПуВ 1х6",
    "ПБГВВ 2х1,5",
)


def test_periodic_letter_four_marks_normalized() -> None:
    text = _INLINE_OCR
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) == 4
    def _norm(s: str) -> str:
        return s.replace(" ", "").lower().replace("x", "х")

    for expected in _EXPECTED:
        assert any(
            _norm(expected) in _norm(m) for m in marks
        ), f"нет {expected!r} в {marks}"


_GARBLED_TABLE = """периодические испытания
13х4ок (N, PE)-0,66    16470,00    13500,00    2970,00    40
2    ПВСнг(А)-LS 3х2,5064500,00400
3    АПуВ 1х6    35685,00    29250,00    6435,00    50
4    ПБГВВ 2х1,522500,0040"""


def test_periodic_garbled_table_without_periodic_word() -> None:
    """Только строки таблицы — без заголовка «периодические испытания»."""
    table_only = _GARBLED_TABLE.split("\n", 1)[1]
    marks = [m.mark for m in find_cable_marks(table_only)]
    assert len(marks) == 4
    assert marks[0].startswith("ВВГнг(А)")


def test_periodic_garbled_table_with_prices() -> None:
    """Таблица из GUI/OCR со склеенными ценами и номером строки «1»."""
    marks = [m.mark for m in find_cable_marks(_GARBLED_TABLE)]
    assert len(marks) == 4
    assert marks[0].startswith("ВВГнг(А)")
    assert "3х4ок" in marks[0].replace("x", "х")
    assert marks[1] == "ПВСнг(А)-LS 3х2,50"
    assert any(m.replace("x", "х") == "АПуВ 1х6" for m in marks)
    assert any(m == "ПБГВВ 2х1,5" for m in marks)