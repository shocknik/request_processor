"""Тесты нормализации OCR в марках кабелей."""

from __future__ import annotations

from request_processor.extraction.ocr_mark_normalizer import (
    latin_to_cyrillic_in_brand,
    normalize_mark_after_ocr,
)
from request_processor.extraction.pdf_extractor import find_cable_marks


def test_kcbur_to_ksbng() -> None:
    assert latin_to_cyrillic_in_brand("KCBur(A)") == "КСБнг(А)"


def test_normalize_full_mark_with_size() -> None:
    result = normalize_mark_after_ocr("KCBur(A)-LS 3x2,50")
    assert result.startswith("КСБнг(А)")
    assert "3" in result


def test_mostly_latin_brand_gets_cyrillic() -> None:
    assert normalize_mark_after_ocr("KCBur(A)-LS") == "КСБнг(А)-LS"


def test_kaluga_brands_normalized() -> None:
    result = normalize_mark_after_ocr("BBI-MHr(A) 3x40K(N,PE)-0,66")
    assert result.startswith("ВВГнг(А)")
    assert "3х4ок" in result
    assert normalize_mark_after_ocr("NBCur(A)-LS 3x2,50").startswith("ПВСнг(А)-LS")
    assert normalize_mark_after_ocr("AllyB 1x6") == "АПуВ 1х6"
    assert normalize_mark_after_ocr("NBIBB 2x1,5") == "ПБГВВ 2х1,5"


def test_lan_mark_preserves_cat() -> None:
    raw = "СПЕЦЛАН F/UTP Cat 5e ZH нг(A)-HF 2x2x0,52"
    result = normalize_mark_after_ocr(raw)
    assert "Cat" in result or "cat" in result.lower()
    assert "UTP" in result


def test_strip_table_price_glue_preserves_size() -> None:
    assert normalize_mark_after_ocr("ПВСнг(А)-LS 3х2,50") == "ПВСнг(А)-LS 3х2,50"
    assert normalize_mark_after_ocr("ПВСнг(А)-LS 3х2,5064500,00400") == "ПВСнг(А)-LS 3х2,50"
    assert normalize_mark_after_ocr("ПБГВВ 2х1,522500,0040") == "ПБГВВ 2х1,5"
    assert normalize_mark_after_ocr("АПуВ 1х6    35685,00    29250,00") == "АПуВ 1х6"