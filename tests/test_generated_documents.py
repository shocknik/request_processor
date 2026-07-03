"""Тесты журнала generated_documents (PR-3)."""

from __future__ import annotations

from pathlib import Path

from request_processor.persistence.sqlite_repo import (
    build_default_hours_map,
    create_order_from_kp,
    init_db,
    list_generated_documents,
    save_calculation,
    save_generated_document,
)
from request_processor.calculation.cost_calculator import calculate_cost


def _save_demo_calc(db: Path, mark: str = "ВВГ 3х2,5") -> int:
    hours = build_default_hours_map(db)
    calc = calculate_cost(mark, ["solar_radiation"], hours, db)
    return save_calculation(calc, db)


def test_save_and_list_generated_document(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    doc_id = save_generated_document(
        doc_type="kp",
        file_path=str(tmp_path / "КП_test.docx"),
        order_id=None,
        db_path=db,
    )
    assert doc_id > 0
    rows = list_generated_documents(doc_type="kp", db_path=db)
    assert len(rows) == 1
    assert rows[0]["doc_type"] == "kp"
    assert "КП_test.docx" in rows[0]["file_path"]


def test_create_order_records_kp_document(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    calc_id = _save_demo_calc(db)
    kp_path = tmp_path / "КП_demo.docx"
    kp_path.write_bytes(b"docx")

    order_id = create_order_from_kp(
        customer_name="ООО Тест",
        subject="Испытания",
        calculation_ids=[calc_id],
        kp_output_path=str(kp_path),
        db_path=db,
    )

    docs = list_generated_documents(order_id=order_id, db_path=db)
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "kp"
    assert docs[0]["order_id"] == order_id