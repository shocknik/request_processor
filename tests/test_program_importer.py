"""Импорт программ испытаний из DOCX."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from request_processor.generation.program_importer import (
    import_program_from_docx,
    parse_program_docx,
)
from request_processor.persistence.sqlite_repo import (
    get_test_program,
    init_db,
    list_test_programs,
    match_program_items_to_price,
)


def _make_sample_program_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("УТВЕРЖДАЮ")
    doc.add_paragraph("ПРОГРАММА")
    doc.add_paragraph(
        "приемосдаточных испытаний кабеля марки СПЕЦЛАН F/UTP Cat 5е 4x2x0,52, "
        "изготовленного по ТУ 16.К99-058-2014"
    )
    table = doc.add_table(rows=4, cols=4)
    headers = [
        ("№ п/п", "Вид испытаний и проверок", "технических требований", "методов испытаний"),
        ("1.", "Проверка конструкции", "1.2.2, 1.2.3", "4.2.1"),
        ("2.", "Определение электрического сопротивления жил", "1.4.1", "4.3.1"),
        ("3.", "Испытание напряжением", "1.4.5", "4.3.5"),
    ]
    for ri, row_vals in enumerate(headers):
        for ci, val in enumerate(row_vals):
            table.rows[ri].cells[ci].text = val
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def test_parse_program_docx_tables(tmp_path: Path) -> None:
    docx = _make_sample_program_docx(tmp_path / "prog.docx")
    parsed = parse_program_docx(docx)
    assert len(parsed.items) >= 2
    assert any("сопротивления" in it.name.lower() for it in parsed.items)
    assert "16.К99" in (parsed.tu_ref or "") or "ТУ" in (parsed.tu_ref or "")


def test_import_program_to_db(tmp_path: Path) -> None:
    db = tmp_path / "p.db"
    init_db(db)
    docx = _make_sample_program_docx(tmp_path / "prog.docx")
    result = import_program_from_docx(docx, db_path=db, match_price=True)
    assert result["program_id"] >= 1
    assert result["items_count"] >= 2
    prog = get_test_program(result["program_id"], db_path=db)
    assert prog is not None
    assert len(prog["items"]) >= 2
    rows = list_test_programs(db_path=db)
    assert len(rows) >= 1


def test_match_price_runs(tmp_path: Path) -> None:
    db = tmp_path / "p.db"
    init_db(db)
    docx = _make_sample_program_docx(tmp_path / "prog.docx")
    result = import_program_from_docx(docx, db_path=db, match_price=False)
    stats = match_program_items_to_price(result["program_id"], db_path=db)
    assert "matched" in stats and "unmatched" in stats
