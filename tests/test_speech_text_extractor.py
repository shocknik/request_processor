"""Свободный текст: марки без NхM, пункты ТУ (кейсы work PC 28–31.07)."""

from __future__ import annotations

from request_processor.extraction.pdf_extractor import extract_from_text
from request_processor.extraction.speech_text_extractor import (
    extract_tu_clauses,
    find_speech_marks,
)
from request_processor.extraction.test_type_extractor import detect_test_type
from request_processor.validation.extraction_validator import validate_extraction

_KAGE = """
Никита, добрый день!
У нас в работе кабель КАГЭ с поставкой на АЭС АККУЮ.
Направляю Вам ТУ на этот кабель. Жду информацию по стоимости)
"""

_MGLF = """
Добрый день!
Просим сообщить стоимость и сроки проведения сертификационных испытаний
образца провода монтажного марки МГЛФ на соответствие
ТУ 16.К05-025-2003 «Провода монтажные. Технические условия»
пункты 1.1.3, 1.2.1, 1.2.2, 1.4.1.1, 1.4.1.2, 1.4.1.3,
1.5.1.2, 1.5.1.3, 1.5.1.4, 1.5.1.7, 1.5.2, 1.5.3, 1.8.1.
ТУ во вложении.
"""

_ENERGY = """
ТУ во вложении
Требование — п. 1.6.6 ТУ
Метод — 4.5.7 ТУ
Кабель  — Энергия-ВЗ-МКВЭклВКснг(А)-FRLS-УФ
Возможно увеличение количества образцов,
"""


def test_speech_kage_brand_only() -> None:
    marks = [m.mark for m in find_speech_marks(_KAGE)]
    assert any("КАГЭ" in m for m in marks)


def test_speech_mglf_with_clauses_and_tu() -> None:
    found = find_speech_marks(_MGLF)
    assert any(m.mark == "МГЛФ" for m in found)
    m = next(x for x in found if x.mark == "МГЛФ")
    assert m.document and "16.К05" in m.document
    assert m.requirements_raw
    assert "1.1.3" in m.requirements_raw
    assert "1.8.1" in (m.requirements_raw or "")
    clauses = extract_tu_clauses(_MGLF)
    assert "1.4.1.1" in clauses
    assert len(clauses) >= 10


def test_speech_energy_fire_class_no_size() -> None:
    found = find_speech_marks(_ENERGY)
    assert any("Энергия" in m.mark and "FRLS" in m.mark.upper() for m in found)
    m = next(x for x in found if "Энергия" in x.mark)
    assert m.requirements_raw
    assert "1.6.6" in m.requirements_raw
    assert "4.5.7" in m.requirements_raw


def test_extract_from_text_work_samples_end_to_end() -> None:
    for sample, needle in (
        (_KAGE, "КАГЭ"),
        (_MGLF, "МГЛФ"),
        (_ENERGY, "Энергия"),
    ):
        result = extract_from_text(sample, source_label="customer_speech")
        marks = " ".join(m.mark for m in result.cable_marks)
        assert needle in marks, marks
        report = validate_extraction(result)
        accepted = [m for m in report.marks if m.accepted]
        assert accepted, f"no accepted marks for {needle}: {report.marks}"
        assert not report.block_confirm or any(
            m.accepted for m in report.marks
        )


def test_detect_test_type_sert() -> None:
    assert detect_test_type(_MGLF) == "сертификационные"


def test_extract_from_text_still_finds_sized_marks() -> None:
    """Регрессия: ВВГнг(А)-LS 3х1,5 не ломаем."""
    text = """
    Добрый день. Просим провести периодические испытания кабеля
    ВВГнг(А)-LS 3х1,5 и ПВСнг(А)-LS 3х2,5.
    Заказчик: ООО «Ромашка», ИНН 7701234567.
    """
    result = extract_from_text(text)
    marks = " ".join(m.mark for m in result.cable_marks)
    assert "ВВГ" in marks or "ПВС" in marks
