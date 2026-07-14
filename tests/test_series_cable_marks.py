"""FLEXICORE marks from application table text (clean + OCR-noisy)."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import (
    _fix_series_cable_ocr,
    find_cable_marks,
)


def test_flexicore_table_lines() -> None:
    text = (
        "FLEXICORE 100 | ТУ 3550-014-75175160-2022\n"
        "FLEXICORE 110 нг(A)-LS | ТУ 3550-014-75175160-2022\n"
        "FLEXICORE LiYCY | ТУ 3550-015-75175160-2024\n"
        "H07RN-F RU | ТУ 3550-010-75175160-2021"
    )
    marks = [m.mark for m in find_cable_marks(text)]
    assert len(marks) >= 4
    assert any(m.startswith("FLEXICORE 100") for m in marks)
    assert any("LiYCY" in m for m in marks)
    assert any(m.startswith("H07RN-F") for m in marks)


def test_flexicore_with_voltage() -> None:
    text = "FLEXICORE 105 CY нг(A)-LS 0,6/1 кВ | ТУ 3550-014"
    marks = [m.mark for m in find_cable_marks(text)]
    assert any("0,6/1" in m and "105 CY" in m for m in marks)


def test_flexicore_combine_fire_and_voltage_from_split_ocr() -> None:
    """OCR often splits full GT row into fire-only + voltage-only lines (35s)."""
    text = (
        "FLEXICORE 100 нг(A)-LS | ТУ 3550-014\n"
        "FLEXICORE 100 0,6/1 кВ | ТУ 3550-014\n"
        "FLEXICORE 105 CY нг(A)-LS | ТУ 3550-014\n"
        "FLEXICORE 105 CY 0,6/1 кВ | ТУ 3550-014\n"
    )
    marks = {m.mark for m in find_cable_marks(text)}
    assert "FLEXICORE 100 нг(A)-LS 0,6/1 кВ" in marks
    assert "FLEXICORE 105 CY нг(A)-LS 0,6/1 кВ" in marks


def test_h07rn_ocr_variants_normalize() -> None:
    for raw in ("H07RN-F RU", "H07RN F RU", "H07RNF RU", "HO7RN-F RU"):
        marks = [m.mark for m in find_cable_marks(raw + " | ТУ 3550")]
        assert any(m == "H07RN-F RU" for m in marks), raw


def test_flexicore_ocr_ur_and_kb_fix() -> None:
    """Tesseract often reads нг as ur and кВ as kB after orientation fix."""
    raw = (
        "FLEXICORE 100 ur(A)-LS TY 3550-014-75175 160-2022\n"
        "FLEXICORE 100 0,6/1 kB TY 3550-014\n"
        "FLEXICORE FLAT ur(A)-LS TY 3550\n"
        "FLEXICORE 130 H ur(A)-HF | TY 3550-017\n"
    )
    fixed = _fix_series_cable_ocr(raw)
    assert "нг(A)" in fixed
    assert "кВ" in fixed
    marks = [m.mark for m in find_cable_marks(raw)]
    assert any(m == "FLEXICORE 100 нг(A)-LS" for m in marks)
    assert any("0,6/1 кВ" in m for m in marks)
    assert any("FLAT" in m and "нг(A)" in m for m in marks)


def test_flexicore_full_gt_set_from_clean_text() -> None:
    """All 16 GT lines (Word table) must parse."""
    text = """
FLEXICORE 100 | ТУ 3550-014-75175160-2022
FLEXICORE 100 0,6/1 кВ | ТУ 3550-014-75175160-2022
FLEXICORE 100 нг(A)-LS | ТУ 3550-014-75175160-2022
FLEXICORE 100 нг(A)-LS 0,6/1 кВ | ТУ 3550-014-75175160-2022
FLEXICORE 110 | ТУ 3550-014-75175160-2022
FLEXICORE 110 нг(A)-LS | ТУ 3550-014-75175160-2022
FLEXICORE FLAT нг(A)-LS | ТУ 3550-014-75175160-2022
FLEXICORE 115 CY | ТУ 3550-014-75175160-2022
FLEXICORE 115 CY нг(A)-LS | ТУ 3550-014-75175160-2022
FLEXICORE 105 CY 0,6/1 кВ | ТУ 3550-014-75175160-2022
FLEXICORE 105 CY нг(A)-LS 0,6/1 кВ | ТУ 3550-014-75175160-2022
FLEXICORE LiYCY | ТУ 3550-015-75175160-2024
FLEXICORE LiYY | ТУ 3550-015-75175160-2024
FLEXICORE 130 H нг(A)-HF | ТУ 3550-017-75175160-2023
FLEXICORE 135 CH нг(A)-HF | ТУ 3550-017-75175160-2023
H07RN-F RU | ТУ 3550-010-75175160-2021
"""
    marks = {m.mark for m in find_cable_marks(text)}
    expected = {
        "FLEXICORE 100",
        "FLEXICORE 100 0,6/1 кВ",
        "FLEXICORE 100 нг(A)-LS",
        "FLEXICORE 100 нг(A)-LS 0,6/1 кВ",
        "FLEXICORE 110",
        "FLEXICORE 110 нг(A)-LS",
        "FLEXICORE FLAT нг(A)-LS",
        "FLEXICORE 115 CY",
        "FLEXICORE 115 CY нг(A)-LS",
        "FLEXICORE 105 CY 0,6/1 кВ",
        "FLEXICORE 105 CY нг(A)-LS 0,6/1 кВ",
        "FLEXICORE LiYCY",
        "FLEXICORE LiYY",
        "FLEXICORE 130 H нг(A)-HF",
        "FLEXICORE 135 CH нг(A)-HF",
        "H07RN-F RU",
    }
    missing = expected - marks
    assert not missing, f"missing {missing}; got {sorted(marks)}"
