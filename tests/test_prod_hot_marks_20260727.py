"""Регрессия prod 27.07.2026: U/UTP generic LAN + glued «марки ЛПМФм10х0,08».

Источник: C:/Users/User/Downloads/prod2707 (Obsidian 65).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from request_processor.extraction.organization_extractor import (
    suggest_customer_from_source_path,
)
from request_processor.extraction.pdf_extractor import find_cable_marks
from request_processor.generation.document_pack import safe_filename_part


def _norm(mark: str) -> str:
    text = mark.lower().replace("х", "x").replace("×", "x")
    return re.sub(r"\s+", "", text)


# Фрагменты текста из prod extract JSON (не полные ТУ/PDF).
_SUPR_TZ_SNIPPET = (
    "Требования к испытанию кабельной продукции:\n"
    "• Кабельная продукция, U/UTP cat 5e 2x2x0.52 PE – 2 шт,"
    "U/UTP cat 5e 4x2x0.52 PE\n"
    "– 2 шт. для каждого из предложенного производителя, должна иметь\n"
    "положительный протокол испытания на соответствие требованиям текущего\n"
    "Технического задания."
)

_LPMF_DOCX_SNIPPET = (
    "провод марки ЛПМФм10х0,08\n"
    "на соответствие требованиям ТУ 27.32.13-022-17512508-2026\n"
    "Число* и се-чение токо-проводящих жил, мм2 Размеры, мм\n"
    "10х0,08 0,8±0,1 0,10±0,02 1,25±0,1\n"
)


def test_prod_supr_generic_utp_marks() -> None:
    marks = find_cable_marks(_SUPR_TZ_SNIPPET)
    norms = [_norm(m.mark) for m in marks]
    assert any("u/utp" in n and "2x2x0.52" in n for n in norms), marks
    assert any("u/utp" in n and "4x2x0.52" in n for n in norms), marks
    assert len(marks) >= 2


def test_prod_lpmf_glued_mark_after_marki() -> None:
    marks = find_cable_marks(_LPMF_DOCX_SNIPPET)
    norms = [_norm(m.mark) for m in marks]
    assert any("лпмфм" in n and "10x0,08" in n for n in norms), marks


@pytest.mark.parametrize(
    "sample,size_frag",
    [
        ("U/UTP cat 5e 2x2x0.52 PE", "2x2x0.52"),
        ("F/UTP Cat 5e 4x2x0,52", "4x2x0"),
        ("S/FTP cat 6a 4x2x0.57 PE", "4x2x0.57"),
    ],
)
def test_generic_lan_inline(sample: str, size_frag: str) -> None:
    found = find_cable_marks(f"продукция: {sample} — 2 шт.")
    assert found, sample
    joined = " ".join(_norm(m.mark) for m in found)
    # size must remain; shield may get light OCR latin→cyrillic (S/FТР)
    assert _norm(size_frag) in joined, (found, joined)


def test_glued_vs_spaced_lpmf() -> None:
    glued = find_cable_marks("провод марки ЛПМФм10х0,08 на соответствие")
    spaced = find_cable_marks("провод марки ЛПМФм 10х0,08 на соответствие")
    assert glued and spaced
    assert _norm(glued[0].mark) == _norm(spaced[0].mark)


def test_safe_filename_part_quotes() -> None:
    assert " " not in safe_filename_part('ООО «СУПР»') or "_" in safe_filename_part(
        'ООО «СУПР»'
    )
    out = safe_filename_part('ООО «СУПР»')
    assert "ООО" in out and "СУПР" in out
    assert " _" not in out and "_ " not in out
    assert safe_filename_part("") == "заказ"
    assert safe_filename_part("", default="заказчик") == "заказчик"


def test_path_hint_supr() -> None:
    path = Path(
        r"W:/Обработка заявок/Расчёты для заказчиков/SUPR/2026/"
        r"Требование к испытанию кабельной продукции.pdf"
    )
    assert suggest_customer_from_source_path(path) == "SUPR"


def test_path_hint_anosert() -> None:
    path = Path(
        r"W:/Обработка заявок/Расчёты для заказчиков/"
        r"АНО по сертификации Электросерт/2026/ЛПМФм/испытания.docx"
    )
    hint = suggest_customer_from_source_path(path)
    assert hint
    assert "Электросерт" in hint or "АНО" in hint
    assert "ЛПМФм" not in hint
    assert hint != "2026"
