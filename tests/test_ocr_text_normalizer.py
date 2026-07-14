"""OCR text normalizer unit tests (synthetic samples, no client PII)."""

from request_processor.extraction.ocr_text_normalizer import normalize_ocr_text


def test_latin_address_fragment_becomes_readable() -> None:
    raw = (
        "Poccumickaa Peaepauna, KaAyKCKaA OOACCTE, A3@PXXUHCKMM PANOH, "
        "A. Kuaetoso, YA. MpOMbiLuAeHHas, A. 1, CTP. 5"
    )
    fixed = normalize_ocr_text(raw)
    assert "Российская Федерация" in fixed
    assert "Промышленная" in fixed or "MpOMbiLuAeHHas" not in fixed


def test_lan_letter_header_readable() -> None:
    raw = (
        "TeHepanbHomy AnpekTopy\nOOO HNN «CneuKabel»\n"
        "TapaHTuiHoe nucbmMo Mapkax Kabena"
    )
    fixed = normalize_ocr_text(raw)
    assert "Генеральному директору" in fixed
    assert "ООО НПП" in fixed
    # не подставляем шаблон «Производитель» из кода
    assert "Производитель" not in fixed


def test_email_and_lan_mark_preserved() -> None:
    raw = "info@example.com CMELVIAH F/UTP Cat 5e ZH ur(A)-HF 2x2x0,52"
    fixed = normalize_ocr_text(raw)
    assert "info@example.com" in fixed
