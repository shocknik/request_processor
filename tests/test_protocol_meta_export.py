"""Экспорт JSON-каркаса протокола для protocol_generator."""

from __future__ import annotations

import json
from pathlib import Path

from request_processor.generation.protocol_meta_export import (
    build_protocol_meta_json,
    export_protocol_meta_for_order,
)
from request_processor.models import OrganizationExtract, TestItemCreate
from request_processor.persistence.sqlite_repo import (
    add_test_item,
    create_order_from_kp,
    get_connection,
    init_db,
    upsert_organization,
)


def _seed_order(db: Path) -> int:
    init_db(db)
    add_test_item(
        TestItemCreate(
            code="meta_test_res",
            name="Электрическое сопротивление ТПЖ unit",
            base_cost=100.0,
            category="прочее",
            rule_type="fixed",
            method="ГОСТ 7229-76",
        ),
        db,
    )
    upsert_organization(
        OrganizationExtract(name="ООО Заказчик Meta", role="customer", org_type="unknown"),
        db_path=db,
    )
    upsert_organization(
        OrganizationExtract(
            name="ООО Завод Meta", role="manufacturer", org_type="manufacturer"
        ),
        db_path=db,
    )
    with get_connection(db) as conn:
        cur = conn.execute(
            """
            INSERT INTO calculations
                (mark, parsed_mark, total_cost_without_vat, vat_rate,
                 total_cost_with_vat, source, output_path, created_at)
            VALUES ('ВВГнг(А) 3х2,5', '{}', 100, 0.22, 122, 'test', NULL, datetime('now'))
            """
        )
        cid = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO calculation_lines
                (calculation_id, test_item_id, test_name, base_cost, multiplier,
                 quantity, hours, final_cost, note)
            VALUES (?, NULL, 'Электрическое сопротивление ТПЖ unit', 100, 1, 1, NULL, 100, NULL)
            """,
            (cid,),
        )
    order_id = create_order_from_kp(
        customer_name="ООО Заказчик Meta",
        manufacturer_name="ООО Завод Meta",
        subject="Приемосдаточные испытания",
        note=None,
        calculation_ids=[cid],
        kp_output_path=str(db.parent / "fake_kp.docx"),
        db_path=db,
    )
    return order_id


def test_build_protocol_meta_has_primary_and_empty_results(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    order_id = _seed_order(db)
    data = build_protocol_meta_json(order_id, db_path=db)
    assert "PRIMARY" in data
    assert data["3"]["Информация о заказчике"]["наименование: "]
    results = data["10"]["Результаты испытаний"]
    assert results
    group = next(iter(results.values()))
    case = next(iter(group.values()))
    crit = case["Критерии годности: "][0]
    assert crit["Фактический результат"] == ""
    assert data["_meta"]["measured_values"] is False


def test_export_writes_file(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    order_id = _seed_order(db)
    out = tmp_path / "out.json"
    path = export_protocol_meta_for_order(order_id, output_path=out, db_path=db)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["5"]["Информация об объекте испытаний"]["ID: "] == str(order_id)
