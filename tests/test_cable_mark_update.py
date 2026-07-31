"""Редактор справочника марок: update_cable_mark (ТЗ 70, волна C)."""

from __future__ import annotations

from pathlib import Path

from request_processor.models import CableMarkRecord
from request_processor.persistence.sqlite_repo import (
    get_cable_mark_by_id,
    init_db,
    list_cable_marks,
    update_cable_mark,
    upsert_cable_mark,
)


def test_update_cable_mark_fields_and_id_stable(tmp_path: Path) -> None:
    db = tmp_path / "marks.db"
    init_db(db)
    mid = upsert_cable_mark(
        CableMarkRecord(
            full_mark="МГЛФ",
            brand="МГЛФ",
            fire_class=None,
            cores_count=1,
            structural_element_type="жила",
            structural_elements_count=1,
            characteristic_size=1.0,
            size_unit="mm",
            document=None,
            source="test",
        ),
        db_path=db,
    )
    assert mid > 0

    result = update_cable_mark(
        mid,
        full_mark="МГЛФ 1×0,35",
        brand="МГЛФ",
        fire_class=None,
        cores_count=1,
        structural_element_type="жила",
        structural_elements_count=1,
        characteristic_size=0.35,
        size_unit="mm2",
        document="ТУ 16.К05-025-2003",
        db_path=db,
    )
    assert result["ok"] is True
    assert result["id"] == mid
    assert result["full_mark"] == "МГЛФ 1×0,35"

    row = get_cable_mark_by_id(mid, db)
    assert row is not None
    assert row["full_mark"] == "МГЛФ 1×0,35"
    assert row["document"] == "ТУ 16.К05-025-2003"
    assert float(row["characteristic_size"]) == 0.35
    assert list_cable_marks(search="МГЛФ", db_path=db)


def test_update_cable_mark_duplicate_rejected(tmp_path: Path) -> None:
    db = tmp_path / "marks2.db"
    init_db(db)
    a = upsert_cable_mark(
        CableMarkRecord(
            full_mark="ААА",
            brand="ААА",
            cores_count=1,
            structural_element_type="жила",
            structural_elements_count=1,
            characteristic_size=1.0,
            size_unit="mm2",
        ),
        db_path=db,
    )
    b = upsert_cable_mark(
        CableMarkRecord(
            full_mark="БББ",
            brand="БББ",
            cores_count=1,
            structural_element_type="жила",
            structural_elements_count=1,
            characteristic_size=1.0,
            size_unit="mm2",
        ),
        db_path=db,
    )
    result = update_cable_mark(
        b,
        full_mark="ААА",
        brand="БББ",
        cores_count=1,
        characteristic_size=1.0,
        size_unit="mm2",
        db_path=db,
    )
    assert result["ok"] is False
    assert result["reason"] == "duplicate_mark"
    assert get_cable_mark_by_id(a, db)["full_mark"] == "ААА"
