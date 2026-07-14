"""Свободный текст / речь заказчика → extract_from_text."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import extract_from_text
from request_processor.validation.extraction_validator import validate_extraction


def test_extract_from_text_marks_and_org() -> None:
    text = """
    Добрый день. Просим провести периодические испытания кабеля
    ВВГнг(А)-LS 3х1,5 и ПВСнг(А)-LS 3х2,5.
    Заказчик: ООО «Ромашка», ИНН 7701234567.
    Производитель: ООО «КабельПром».
    """
    result = extract_from_text(text)
    assert result.source_type == "text"
    assert result.source_path.startswith("text://")
    assert len(result.cable_marks) >= 1
    marks = " ".join(m.mark for m in result.cable_marks)
    assert "ВВГ" in marks or "ПВС" in marks
    report = validate_extraction(result)
    assert report.marks


def test_extract_from_text_empty_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        extract_from_text("   ")
