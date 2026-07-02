"""
Извлечение марок из таблицы направления в ИЛ (table-first).

Приоритет над regex по плоскому тексту PDF: ячейки таблицы содержат
корректные марки, ТУ и контролируемые показатели.
"""

from __future__ import annotations

import re

from .cable_mark_parser import extract_document_from_text
from .models import CableMarkMatch

_PRODUCT_HEADER = re.compile(r"наименован\w*\s+продукц", re.IGNORECASE)
_INDICATORS_HEADER = re.compile(r"контролируем\w*\s+показател", re.IGNORECASE)
_REQUIREMENTS_HEADER = re.compile(
    r"испытан\w*\s+следует|требован\w*\s+нормативн", re.IGNORECASE
)
_DATA_ROW_NUM = re.compile(r"^\d+$")


def _is_column_number_row(row: list[str]) -> bool:
    cells = [c.strip() for c in row if c.strip()]
    return bool(cells) and all(_DATA_ROW_NUM.match(c) and int(c) <= 10 for c in cells)


def _normalize_cell(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\n", " ").strip())


def _header_row_index(table: list[list[str]]) -> int | None:
    for idx, row in enumerate(table[:4]):
        joined = " ".join(row).lower()
        if _PRODUCT_HEADER.search(joined) and (
            _INDICATORS_HEADER.search(joined) or _REQUIREMENTS_HEADER.search(joined)
        ):
            return idx
    return None


def _column_map(header_row: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        norm = _normalize_cell(cell).lower()
        if _PRODUCT_HEADER.search(norm):
            cols["product"] = idx
        elif _INDICATORS_HEADER.search(norm):
            cols["indicators"] = idx
        elif _REQUIREMENTS_HEADER.search(norm):
            cols["requirements"] = idx
    return cols


def is_direction_table(table: list[list[str]]) -> bool:
    """Таблица направления в ИЛ: заголовки продукции и показателей."""
    if not table or len(table) < 3:
        return False
    header_idx = _header_row_index(table)
    if header_idx is None:
        return False
    cols = _column_map(table[header_idx])
    return "product" in cols and ("indicators" in cols or "requirements" in cols)


def _data_rows(table: list[list[str]], header_idx: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table[header_idx + 1 :]:
        if not row or not any(cell.strip() for cell in row):
            continue
        if _is_column_number_row(row):
            continue
        first = row[0].strip()
        if _DATA_ROW_NUM.match(first):
            rows.append(row)
    return rows


def _extract_mark_from_product(product_text: str) -> CableMarkMatch | None:
    from .pdf_extractor import find_cable_marks

    normalized = _normalize_cell(product_text)
    if not normalized:
        return None
    matches = find_cable_marks(normalized)
    if not matches:
        return None
    best = matches[0]
    return best.model_copy(update={"context": normalized[:200]})


def _row_to_match(row: list[str], cols: dict[str, int]) -> CableMarkMatch | None:
    product_idx = cols.get("product", 1)
    req_idx = cols.get("requirements")
    ind_idx = cols.get("indicators")

    if product_idx >= len(row):
        return None

    product_text = row[product_idx]
    match = _extract_mark_from_product(product_text)
    if match is None:
        return None

    req_text = row[req_idx] if req_idx is not None and req_idx < len(row) else ""
    ind_text = row[ind_idx] if ind_idx is not None and ind_idx < len(row) else ""

    document = (
        extract_document_from_text(req_text)
        or extract_document_from_text(ind_text)
        or match.document
    )

    requirements_raw: str | None = None
    if ind_idx is not None and ind_idx < len(row) and row[ind_idx].strip():
        requirements_raw = _normalize_cell(row[ind_idx])
    elif req_blob:
        requirements_raw = req_blob

    return match.model_copy(
        update={
            "document": document,
            "requirements_raw": requirements_raw,
        }
    )


def extract_marks_from_direction_table(table: list[list[str]]) -> list[CableMarkMatch]:
    """Парсит одну таблицу направления. Пустой список, если таблица не подходит."""
    if not is_direction_table(table):
        return []

    header_idx = _header_row_index(table)
    assert header_idx is not None
    cols = _column_map(table[header_idx])
    if "product" not in cols:
        return []

    marks: list[CableMarkMatch] = []
    seen: set[str] = set()
    for row in _data_rows(table, header_idx):
        match = _row_to_match(row, cols)
        if match is None:
            continue
        key = match.mark.lower()
        if key in seen:
            continue
        seen.add(key)
        marks.append(match)

    return _apply_shared_tu(marks)


def _apply_shared_tu(marks: list[CableMarkMatch]) -> list[CableMarkMatch]:
    """Если в направлении одна ТУ — подставляет её в строки без ТУ."""
    tus = [m.document for m in marks if m.document and m.document.upper().startswith("ТУ")]
    if not tus:
        return marks
    shared = max(set(tus), key=tus.count)
    return [
        m.model_copy(update={"document": shared})
        if not (m.document and m.document.upper().startswith("ТУ"))
        else m
        for m in marks
    ]


def extract_marks_from_tables(tables: list[list[list[str]]]) -> list[CableMarkMatch]:
    """Собирает марки из всех таблиц направления в документе."""
    all_marks: list[CableMarkMatch] = []
    seen: set[str] = set()
    for table in tables:
        for match in extract_marks_from_direction_table(table):
            key = match.mark.lower()
            if key in seen:
                continue
            seen.add(key)
            all_marks.append(match)
    return all_marks