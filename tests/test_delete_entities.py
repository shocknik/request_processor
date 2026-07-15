"""Удаление марки / расчёта / заказа / организации из БД."""

from __future__ import annotations

from pathlib import Path

from request_processor.models import OrganizationExtract, TestItemCreate
from request_processor.parsing.cable_mark_parser import parse_cable_mark_record
from request_processor.persistence.sqlite_repo import (
    add_test_item,
    delete_cable_mark,
    delete_calculation,
    delete_organization,
    get_connection,
    init_db,
    list_cable_marks,
    upsert_cable_mark,
    upsert_organization,
)


def test_delete_cable_mark_free(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    init_db(db)
    rec = parse_cable_mark_record("ВВГнг(А) 3х2,5")
    mid = upsert_cable_mark(rec, db)
    assert delete_cable_mark(mid, db)["ok"] is True
    assert list_cable_marks(db_path=db) == []


def test_delete_organization_free(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    init_db(db)
    oid = upsert_organization(
        OrganizationExtract(name="ООО Удалить Тест", role="customer", org_type="unknown"),
        db_path=db,
    )
    assert delete_organization(oid, db)["ok"] is True


def test_delete_calculation(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    init_db(db)
    add_test_item(
        TestItemCreate(
            code="del_test_item",
            name="Удаляемое испытание unit",
            base_cost=10.0,
            category="прочее",
            rule_type="fixed",
        ),
        db,
    )
    # minimal calculation via SQL to avoid full cost pipeline
    with get_connection(db) as conn:
        cur = conn.execute(
            """
            INSERT INTO calculations
                (mark, parsed_mark, total_cost_without_vat, vat_rate,
                 total_cost_with_vat, source, output_path, created_at)
            VALUES ('TEST', '{}', 100, 0.22, 122, 'manual', NULL, datetime('now'))
            """
        )
        cid = cur.lastrowid
    assert delete_calculation(int(cid), db)["ok"] is True
    with get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM calculations").fetchone()["n"]
    assert n == 0
