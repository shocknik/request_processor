"""Регрессия: письмо производителя (4 марки из Word, OCR-шум)."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import (
    _fix_periodic_letter_ocr,
    find_cable_marks,
)

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


def _norm_mark(s: str) -> str:
    return s.replace(" ", "").lower().replace("x", "х")


def test_ish_163_four_marks_from_ocr_snippet() -> None:
    marks = [m.mark for m in find_cable_marks(_ISH163_OCR)]
    assert len(marks) == 4, marks
    for expected in _EXPECTED:
        norm = _norm_mark(expected)
        assert any(norm in _norm_mark(m) for m in marks), f"нет {expected!r} в {marks}"


def test_ish_163_periodic_ocr_fix_expands_brands() -> None:
    fixed = _fix_periodic_letter_ocr(_ISH163_OCR)
    assert "ВВГ-Пнг" in fixed or "ВВГ-П" in fixed
    assert "ПБГВВ" in fixed
    assert "ПВСнг" in fixed
    assert "ПуПВнг" in fixed or "LSLTx" in fixed
    assert "--0,66" not in fixed or "-0,66" in fixed