"""FLEXICORE marks from application table text."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import find_cable_marks


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