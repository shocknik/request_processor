"""prepare-prod-db: прайс и mappings остаются, марки/орг. очищаются."""

from __future__ import annotations

from pathlib import Path

from request_processor.models import OrganizationExtract, TestItemCreate
from request_processor.persistence.sqlite_repo import (
    add_test_item,
    init_db,
    list_cable_marks,
    list_organizations,
    list_test_items,
    prepare_prod_db,
    save_cable_marks_from_matches,
    save_organizations_from_extraction,
    upsert_organization,
)
from request_processor.models import CableMarkMatch


def test_prepare_prod_db_keeps_price_clears_marks(tmp_path: Path) -> None:
    db = tmp_path / "field.db"
    init_db(db)

    # прайс уже может быть из seed/xlsx
    n_before = len(list_test_items(db_path=db))
    if n_before < 1:
        add_test_item(
            TestItemCreate(
                code="demo_x",
                name="Демо",
                price=100.0,
                rule_type="fixed",
            ),
            db_path=db,
        )

    save_cable_marks_from_matches(
        [CableMarkMatch(mark="МКЭШ 2х2х0,35")],
        source="test",
        db_path=db,
    )
    upsert_organization(
        OrganizationExtract(name="ООО Тест", org_type="unknown", role="customer"),
        source="test",
        db_path=db,
    )
    assert list_cable_marks(limit=10, db_path=db)
    assert list_organizations(limit=10, db_path=db)

    result = prepare_prod_db(db, backup=True)
    assert result.get("backup_path")
    assert Path(result["backup_path"]).is_file()
    assert "pre_prod_" in result["backup_path"]
    assert result["kept_test_items"] >= 1
    assert list_cable_marks(limit=10, db_path=db) == []
    assert list_organizations(limit=10, db_path=db) == []
