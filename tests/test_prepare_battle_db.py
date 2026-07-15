"""prepare-battle-db: прайс и mappings остаются, марки/орг. очищаются."""

from __future__ import annotations

from pathlib import Path

from request_processor.models import OrganizationExtract, TestItemCreate
from request_processor.parsing.cable_mark_parser import parse_cable_mark_record
from request_processor.persistence.sqlite_repo import (
    add_test_item,
    get_connection,
    init_db,
    prepare_battle_db,
    upsert_cable_mark,
    upsert_organization,
)


def test_prepare_battle_db_keeps_price_clears_marks(tmp_path: Path) -> None:
    db = tmp_path / "battle.db"
    init_db(db)

    add_test_item(
        TestItemCreate(
            code="unit_test_item",
            name="Тестовое испытание unit",
            base_cost=100.0,
            category="прочее",
            rule_type="fixed",
        ),
        db,
    )
    rec = parse_cable_mark_record("ВВГнг(А) 3х2,5")
    upsert_cable_mark(rec, db)
    upsert_organization(
        OrganizationExtract(
            name="ООО Тест Заказчик",
            role="customer",
            org_type="unknown",
        ),
        db_path=db,
    )

    with get_connection(db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM cable_marks").fetchone()["n"] >= 1
        assert conn.execute("SELECT COUNT(*) AS n FROM organizations").fetchone()["n"] >= 1
        items_before = conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"]
        maps_before = conn.execute("SELECT COUNT(*) AS n FROM test_mappings").fetchone()["n"]

    result = prepare_battle_db(db, backup=True)

    assert result["kept_test_items"] == items_before
    assert result["kept_test_mappings"] == maps_before
    assert result["backup_path"]
    assert Path(result["backup_path"]).exists()

    with get_connection(db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM cable_marks").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM organizations").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"] == items_before
        assert (
            conn.execute("SELECT COUNT(*) AS n FROM test_mappings").fetchone()["n"] == maps_before
        )
        assert (
            conn.execute(
                "SELECT 1 FROM test_items WHERE code = ?",
                ("unit_test_item",),
            ).fetchone()
            is not None
        )
