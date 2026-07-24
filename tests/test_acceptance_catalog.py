"""Волна 1: acceptance_items / clauses / external refs (ТЗ v3)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from request_processor.cli import cli
from request_processor.persistence.sqlite_repo import (
    add_acceptance_item,
    get_acceptance_item,
    init_db,
    list_acceptance_items,
    seed_example_acceptance_catalog,
    show_norm_catalog,
    upsert_norm_document,
)


def test_migrate_and_seed_131(tmp_path: Path) -> None:
    db = tmp_path / "acc.db"
    init_db(db)
    seed_example_acceptance_catalog(db)  # idempotent
    items = list_acceptance_items(
        doc_id="ТУ 27.31.11-131-47273194-2025",
        db_path=db,
    )
    assert len(items) >= 3
    # group_code не обязателен — seed не ставит С1/П1
    assert all(not it.get("group_code") for it in items)
    # маркировка не в прайсе
    mark = next(i for i in items if "маркиров" in (i.get("name_exact") or "").lower())
    assert not mark.get("billable")


def test_clauses_one_by_one_not_range(tmp_path: Path) -> None:
    db = tmp_path / "acc2.db"
    init_db(db)
    upsert_norm_document("ТУ-TEST-001", "Test TU", kind="tu", db_path=db)
    item_id = add_acceptance_item(
        doc_id="ТУ-TEST-001",
        name_exact="Проверка конструкции",
        # два пункта — отдельные связи, не «2.3.1-2.3.6»
        requirement_clauses=["2.3.1", "2.3.2"],
        method_clauses=["5.2"],
        billable=True,
        sort_order=1,
        method_external=[
            {"ext_doc_id": "ГОСТ 12177-86", "ext_clause_or_method": "п. 4"},
        ],
        db_path=db,
    )
    full = get_acceptance_item(item_id, db_path=db)
    assert full is not None
    reqs = [c for c in full["clauses"] if c["role"] == "requirement"]
    meths = [c for c in full["clauses"] if c["role"] == "method_internal"]
    assert {c["clause"] for c in reqs} == {"2.3.1", "2.3.2"}
    assert {c["clause"] for c in meths} == {"5.2"}
    assert len(full["method_external"]) == 1
    assert full["method_external"][0]["ext_doc_id"] == "ГОСТ 12177-86"


def test_show_norm_catalog_join(tmp_path: Path) -> None:
    db = tmp_path / "acc3.db"
    init_db(db)
    cat = show_norm_catalog(
        doc_id="ТУ 27.31.11-131-47273194-2025",
        db_path=db,
    )
    assert cat is not None
    assert cat["doc_id"].startswith("ТУ 27.31.11-131")
    assert len(cat["acceptance_items"]) >= 3
    stretch = next(
        i
        for i in cat["acceptance_items"]
        if "растягивающ" in (i.get("name_exact") or "").lower()
    )
    assert stretch.get("regime") is not None or stretch.get("regime_json")
    assert any(
        e.get("ext_doc_id", "").startswith("ГОСТ 12182")
        for e in stretch.get("method_external") or []
    )


def test_cli_list_and_show(tmp_path: Path) -> None:
    db = tmp_path / "acc4.db"
    init_db(db)
    runner = CliRunner()
    r = runner.invoke(cli, ["list-acceptance-items", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert "растягивающ" in r.output or "затухан" in r.output

    r2 = runner.invoke(
        cli,
        [
            "show-norm-catalog",
            "--doc",
            "ТУ 27.31.11-131-47273194-2025",
            "--db",
            str(db),
        ],
    )
    assert r2.exit_code == 0, r2.output
    assert "acceptance_items:" in r2.output
    assert "2.5.1" in r2.output or "req=" in r2.output

    # id первого item
    items = list_acceptance_items(db_path=db)
    assert items
    rid = int(items[0]["id"])
    r3 = runner.invoke(cli, ["show-acceptance-item", "--id", str(rid), "--db", str(db)])
    assert r3.exit_code == 0, r3.output
    assert "clauses:" in r3.output


def test_cli_add_acceptance_item(tmp_path: Path) -> None:
    db = tmp_path / "acc5.db"
    init_db(db)
    runner = CliRunner()
    r = runner.invoke(
        cli,
        [
            "add-acceptance-item",
            "--doc",
            "ТУ-MANUAL-1",
            "--name",
            "Стойкость к изгибу",
            "--req",
            "2.5.2",
            "--method",
            "5.4.2",
            "--category",
            "periodic",
            "--ext-doc",
            "ГОСТ 12182.3",
            "--no-billable",
            "--db",
            str(db),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "acceptance_item id=" in r.output
    items = list_acceptance_items(doc_id="ТУ-MANUAL-1", db_path=db)
    assert len(items) == 1
    assert not items[0]["billable"]
