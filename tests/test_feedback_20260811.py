"""Регрессии по обратной связи work 11.08.2026 (ТЗ 73).

Combobox antifreeze — отдельный UI-smoke; здесь: марки, path-hint, .doc, subset dedup.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.extraction.organization_extractor import (
    suggest_customer_from_source_path,
)
from request_processor.extraction.pdf_extractor import (
    extract_from_document,
    extract_from_text,
    find_cable_marks,
)


def test_kunrs_series_full_mark() -> None:
    """SERK direction: префикс КУНРС не должен отваливаться."""
    text = (
        "марка КУНРС ЭВнг(A)-FRLS 3х2,5 (N, PE);\n"
        "марка КУНРС УКУнг(А)-FRHF 3х1,5 (N, PE);\n"
        "марка КУНРС Пнг(А)-FRHF 2х1,0 (N)\n"
    )
    marks = find_cable_marks(text)
    joined = " | ".join(m.mark for m in marks)
    assert any("КУНРС" in m.mark and "ЭВнг" in m.mark for m in marks), joined
    assert any("КУНРС" in m.mark and "УКУнг" in m.mark for m in marks), joined
    assert any("КУНРС" in m.mark and "Пнг" in m.mark for m in marks), joined
    # короткие без серии не должны остаться рядом с полными
    assert not any(
        m.mark.startswith("ЭВнг") and "КУНРС" not in m.mark for m in marks
    ), joined
    assert not any(
        m.mark.startswith("УКУнг") and "КУНРС" not in m.mark for m in marks
    ), joined


def test_optical_sp_ok_marks() -> None:
    """Типовые представители ТУ 017 — оптика СП-ОК* без NхM."""
    text = (
        "Кабели (типовые представители) на испытания по ТУ 3587-017-70464675-2015\n"
        "1 СП-ОКСнг(А)-FRHF-М8П-4А-1,5 1 токсичность\n"
        "2 СП-ОКБнг(А)-FRHF-М8П-8А-7,0 2 огнестойкость\n"
        "3 СП-ОКВнг(А)-FRLSLTx-М5П-4М-1,5 1 дым\n"
    )
    marks = find_cable_marks(text)
    joined = " | ".join(m.mark for m in marks)
    assert len(marks) >= 2, joined
    assert any("СП-ОКС" in m.mark for m in marks), joined
    assert any("СП-ОКБ" in m.mark for m in marks), joined


def test_free_text_utp_dedup_pe() -> None:
    """Не плодить U/UTP + без PE + голый brand."""
    letter = (
        "Просим КП. Кабель витая пара — "
        "U/UTP cat 5e 2x2x0.52 PE – 1 шт, "
        "U/UTP cat 5e 4x2x0.52 PE – 1 шт."
    )
    result = extract_from_text(letter, source_label="customer_speech")
    marks = [m.mark for m in result.cable_marks]
    assert len(marks) == 2, marks
    assert all("PE" in m.upper() or "pe" in m for m in marks), marks
    assert not any(m.strip().upper() in {"U/UTP", "UTP"} for m in marks), marks


def test_path_hint_not_windows_username() -> None:
    path = Path(
        r"C:\Users\n.molchanov\Downloads\Тип_представители ТУ 017 ОПТИКА.docx"
    )
    assert suggest_customer_from_source_path(path) == ""


def test_path_hint_still_supr() -> None:
    path = Path(
        r"W:/Обработка заявок/Расчёты для заказчиков/SUPR/2026/"
        r"Требование к испытанию.pdf"
    )
    assert suggest_customer_from_source_path(path) == "SUPR"


def test_doc_format_clear_error(tmp_path: Path) -> None:
    f = tmp_path / "legacy.doc"
    f.write_bytes(b"fake")
    with pytest.raises(ValueError, match=r"\.doc") as ei:
        extract_from_document(f)
    msg = str(ei.value)
    assert "docx" in msg.lower()
    assert "Сохранить" in msg or "сохраните" in msg.lower() or "Word" in msg


def test_org_combo_no_auto_down_in_source() -> None:
    """Страховка: FocusIn/KeyRelease не должны сами слать <Down> без open_list=False default.

    Полный GUI freeze не гоняем здесь — проверяем, что в коде refresh
    по умолчанию open_list=False (антипетля work 10.08).
    """
    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "request_processor"
        / "ui"
        / "tabs"
        / "pdf_tab.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "open_list: bool = False" in text
    assert "_on_focus_in" in text
    assert "open_list=False" in text
    # вызов с open_list=True только внутри явной ветки, не на FocusIn
    assert "FocusIn" in text
