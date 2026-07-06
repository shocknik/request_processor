"""Тесты нормализации сырого OCR-текста заявок."""

from __future__ import annotations

from request_processor.extraction.ocr_text_normalizer import normalize_ocr_text


def test_kaluga_latin_address_becomes_readable() -> None:
    raw = (
        "249841, Poccumickaa Peaepauna, KaAyKCKaA OOACCTE, A3@PXXUHCKMM PANOH, "
        "A. Kuaetoso, YA. MpOMbiLuAeHHas, A. 1, CTP. 5"
    )
    fixed = normalize_ocr_text(raw)
    assert "Калужская область" in fixed
    assert "Дзержинский район" in fixed
    assert "Жилетово" in fixed
    assert "Промышленная" in fixed
    assert "Poccumickaa" not in fixed


def test_speclan_letter_header_readable() -> None:
    raw = (
        "TeHepanbHomy AnpekTopy\nOOO HNN «Cneukabel»\n"
        "Ya. Buptocuuka, A. 6, Kopn. 1-5 nom. XVI, kom. 15,\nMocksa, 107497"
    )
    fixed = normalize_ocr_text(raw)
    assert "Генеральному директору" in fixed
    assert "ООО НПП" in fixed
    assert "Спецкабель" in fixed
    assert "Москва" in fixed
    assert "Бутырская" in fixed


def test_email_and_lan_preserved() -> None:
    raw = "info@spetskabel.ru CMELVIAH F/UTP Cat 5e ZH ur(A)-HF 2x2x0,52"
    fixed = normalize_ocr_text(raw)
    assert "info@spetskabel.ru" in fixed
    assert "Cat 5e" in fixed
    assert "СПЕЦЛАН" in fixed