"""
Импорт программы испытаний из Word (.docx) — полный документ.

Типовая структура ПМИ (Спецкабель и аналоги):
  - абзацы: «ПРОГРАММА», вид испытаний, марка, ТУ
  - таблицы: № | Вид испытаний | Пункты ТУ (требования) | Пункты методов

Не требует OCR; только .docx.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParsedProgramItem:
    sort_order: int
    name: str
    requirement_doc: str = ""
    requirement_clause: str = ""
    method_doc: str = ""
    method_clause: str = ""


@dataclass
class ParsedProgram:
    name: str
    test_type: str = ""
    cable_mark_text: str = ""
    tu_ref: str = ""
    source_path: str = ""
    notes: str = ""
    items: list[ParsedProgramItem] = field(default_factory=list)


_RE_MARK = re.compile(
    r"марки\s+([^\n,]{4,120}?)(?:,|\s+изготовлен|\s+по\s+ТУ|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
_RE_TU = re.compile(
    r"(ТУ\s*[\d.КкA-Za-z\-–—]+(?:\-[\d]+)?(?:\-[\d]+)?)",
    re.IGNORECASE,
)
_RE_TYPE = re.compile(
    r"(при[её]мо\-?сдаточн\w*|периодическ\w*|исследовател\w*|типов\w*|сертификацион\w*)\s+испытан",
    re.IGNORECASE,
)
_RE_NUM_START = re.compile(r"^(\d+)[\.\)]\s*(.+)$")


def _cell_text(cell) -> str:
    return " ".join(p.text.strip() for p in cell.paragraphs if p.text.strip()).strip()


def _is_header_row(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return any(
        k in joined
        for k in (
            "вид испытаний",
            "пункты",
            "№ п/п",
            "n п/п",
            "технических требований",
            "методов испытаний",
        )
    )


def _looks_like_program_table(cells: list[str]) -> bool:
    if len(cells) < 3:
        return False
    joined = " ".join(cells).lower()
    return "вид" in joined or "испытан" in joined or bool(re.match(r"^\d+", cells[0] or ""))


def _split_doc_and_clause(text: str, default_doc: str = "") -> tuple[str, str]:
    """«ТУ 16.К99-058-2014» в doc, «1.4.1, 1.4.2» в clause; иначе всё в clause."""
    text = (text or "").strip()
    if not text:
        return default_doc, ""
    m = _RE_TU.search(text)
    if m:
        doc = m.group(1).replace("–", "-").replace("—", "-")
        clause = (text[: m.start()] + text[m.end() :]).strip(" ,;")
        return doc, clause or text
    # только пункты
    if re.match(r"^[\d\s,.\-–—;]+$", text):
        return default_doc, text.replace("–", "-")
    return default_doc, text


def _parse_tables(doc, default_tu: str) -> list[ParsedProgramItem]:
    items: list[ParsedProgramItem] = []
    order = 0
    for table in doc.tables:
        if not table.rows:
            continue
        # skip pure header-only tables
        data_rows = 0
        for row in table.rows:
            cells = [_cell_text(c) for c in row.cells]
            # merge duplicate cells from colspan
            uniq: list[str] = []
            for c in cells:
                if not uniq or uniq[-1] != c:
                    uniq.append(c)
            cells = uniq
            if len(cells) < 3:
                continue
            if _is_header_row(cells):
                continue
            num_cell, name_cell = cells[0], cells[1]
            req_cell = cells[2] if len(cells) > 2 else ""
            meth_cell = cells[3] if len(cells) > 3 else ""
            if not name_cell or name_cell.lower() in ("вид испытаний и проверок",):
                continue
            # row number
            mnum = re.match(r"^(\d+)", num_cell.strip())
            if mnum:
                order = int(mnum.group(1))
            else:
                order += 1
                # name might start with number
                m2 = _RE_NUM_START.match(name_cell.strip())
                if m2:
                    order = int(m2.group(1))
                    name_cell = m2.group(2)
            name = re.sub(r"\s+", " ", name_cell).strip()
            if len(name) < 3:
                continue
            # skip if first col is not number and name looks like header
            if not mnum and "пункт" in name.lower() and "требован" in name.lower():
                continue
            req_doc, req_clause = _split_doc_and_clause(req_cell, default_tu)
            # method column often only clause numbers; doc may be same TU section 4.x
            meth_doc, meth_clause = _split_doc_and_clause(meth_cell, default_tu)
            if meth_clause and not meth_doc:
                meth_doc = default_tu
            items.append(
                ParsedProgramItem(
                    sort_order=order,
                    name=name,
                    requirement_doc=req_doc,
                    requirement_clause=req_clause,
                    method_doc=meth_doc,
                    method_clause=meth_clause,
                )
            )
            data_rows += 1
        # ignore tables with no data
        if data_rows == 0:
            continue
    # dedupe by (order, name)
    seen: set[tuple[int, str]] = set()
    out: list[ParsedProgramItem] = []
    for it in sorted(items, key=lambda x: x.sort_order):
        key = (it.sort_order, it.name.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _parse_header_from_paragraphs(paragraphs: list[str]) -> dict[str, str]:
    text = "\n".join(paragraphs)
    name = "Программа испытаний"
    for p in paragraphs:
        if re.search(r"п\s*р\s*о\s*г\s*р\s*а\s*м\s*м\s*а", p, re.I) or "ПРОГРАММА" in p.upper():
            # take next non-empty informative lines as title body
            name = "Программа испытаний"
            break
    # full title: first long line with "испытан"
    for p in paragraphs:
        pl = p.lower()
        if "программ" in pl and "испытан" in pl and len(p) > 20:
            name = re.sub(r"\s+", " ", p).strip()[:240]
            break
        if re.search(r"испытан\w+\s+кабел", pl) and len(p) > 30:
            name = re.sub(r"\s+", " ", p).strip()[:240]
            break

    test_type = ""
    mtype = _RE_TYPE.search(text)
    if mtype:
        test_type = mtype.group(1)

    cable_mark = ""
    mm = _RE_MARK.search(text)
    if mm:
        cable_mark = re.sub(r"\s+", " ", mm.group(1)).strip()[:200]
    # fallback: line with Cat / нг / x2x
    if not cable_mark:
        for p in paragraphs:
            if re.search(r"(Cat\s*\d|нг\(|x2x|\d+x\d)", p, re.I) and 10 < len(p) < 200:
                cable_mark = p.strip()[:200]
                break

    tu_refs = _RE_TU.findall(text)
    tu_ref = ", ".join(dict.fromkeys(tu_refs))  # unique preserve order

    return {
        "name": name,
        "test_type": test_type,
        "cable_mark_text": cable_mark,
        "tu_ref": tu_ref,
    }


def parse_program_docx(path: Path | str) -> ParsedProgram:
    """Полный разбор .docx программы испытаний."""
    from docx import Document

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Файл не найден: {file_path}")
    if file_path.suffix.lower() != ".docx":
        raise ValueError("Поддерживается только .docx (не .doc / PDF)")

    doc = Document(str(file_path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    header = _parse_header_from_paragraphs(paragraphs)
    default_tu = ""
    if header["tu_ref"]:
        default_tu = header["tu_ref"].split(",")[0].strip()

    items = _parse_tables(doc, default_tu)
    notes_parts = []
    if not items:
        notes_parts.append("Таблицы с позициями не распознаны — проверьте структуру DOCX.")
    notes_parts.append(f"Абзацев: {len(paragraphs)}, таблиц: {len(doc.tables)}")

    return ParsedProgram(
        name=header["name"] or file_path.stem,
        test_type=header["test_type"],
        cable_mark_text=header["cable_mark_text"],
        tu_ref=header["tu_ref"],
        source_path=str(file_path.resolve()),
        notes="; ".join(notes_parts),
        items=items,
    )


def import_program_from_docx(
    path: Path | str,
    *,
    db_path: Path | str | None = None,
    match_price: bool = True,
) -> dict[str, Any]:
    """Парсит DOCX и сохраняет в БД. Возвращает {program_id, items, matched, …}."""
    from ..persistence.sqlite_repo import (
        DB_PATH_DEFAULT,
        create_test_program,
        match_program_items_to_price,
    )

    db = db_path or DB_PATH_DEFAULT
    parsed = parse_program_docx(path)
    items_payload = [
        {
            "sort_order": it.sort_order,
            "name": it.name,
            "requirement_doc": it.requirement_doc,
            "requirement_clause": it.requirement_clause,
            "method_doc": it.method_doc,
            "method_clause": it.method_clause,
        }
        for it in parsed.items
    ]
    program_id = create_test_program(
        name=parsed.name,
        test_type=parsed.test_type,
        cable_mark_text=parsed.cable_mark_text,
        tu_ref=parsed.tu_ref,
        source_path=parsed.source_path,
        notes=parsed.notes,
        items=items_payload,
        db_path=db,
    )
    match_stats = {"matched": 0, "unmatched": 0}
    if match_price and items_payload:
        match_stats = match_program_items_to_price(program_id, db_path=db)
    return {
        "program_id": program_id,
        "name": parsed.name,
        "test_type": parsed.test_type,
        "cable_mark_text": parsed.cable_mark_text,
        "tu_ref": parsed.tu_ref,
        "items_count": len(parsed.items),
        "matched": match_stats.get("matched", 0),
        "unmatched": match_stats.get("unmatched", 0),
        "source_path": parsed.source_path,
    }
