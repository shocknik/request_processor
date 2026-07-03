"""Тесты определения вида испытаний."""

from __future__ import annotations

from request_processor.extraction.test_type_extractor import (
    build_kp_subject,
    detect_test_type,
    format_test_type_label,
)


def test_periodic_from_letter() -> None:
    text = "Просим Вас провести периодические испытания кабельной продукции"
    assert detect_test_type(text) == "периодические"
    assert format_test_type_label(detect_test_type(text)) == "Периодические"


def test_acceptance_from_letter_145() -> None:
    text = "Просим Вас провести приемо-сдаточные испытания на следующих марках"
    assert detect_test_type(text) == "приемосдаточные"


def test_build_kp_subject() -> None:
    assert "периодических" in build_kp_subject(test_type="Периодические")
    assert "приемосдаточных" in build_kp_subject(
        test_type="Приемосдаточные",
    )


def test_msi_detection() -> None:
    assert detect_test_type("испытания в рамках МСИ") == "мси"