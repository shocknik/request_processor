"""Регрессия: исх 163 — письмо Калуга (4 марки из Word, OCR-шум)."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import find_cable_marks

# Фрагмент реального OCR Tesseract (исх 163.PDF)
_ISH163_OCR = """Nроснм Бас нросестн нерноануескне НСнбIТАаННА КАGеАбНОМ NРоОАУКLIМU
КаGегб СнАОБОМ МАРКК: ТУ 16-705.499- ТОСТ 31996-2012
ББР-Мнг(А) 3х2,50К(N, РЕ)--0,66 2010
флросоа марКн: FIБББ 3х1.5 ТУ 3551-021-
МБСнг(А)}-LS 3х2,50
Мул Бгат (А)-LSLТх 1х6"""

_EXPECTED = (
    "ВВГ-Пнг(А) 3х2,5ок(N, PE)-0,66",
    "ПБГВВ 3х1,5",
    "ПВСнг(А)-LS 3х2,50",
    "ПуПВнг(А)-LSLTx 1х6",
)


def test_ish_163_four_marks_from_ocr_snippet() -> None:
    marks = [m.mark for m in find_cable_marks(_ISH163_OCR)]
    assert len(marks) == 4, marks
    for expected in _EXPECTED:
        norm = expected.replace(" ", "").lower().replace("х", "x")
        assert any(
            norm in m.replace(" ", "").lower().replace("х", "x") for m in marks
        ), f"нет {expected!r} в {marks}"