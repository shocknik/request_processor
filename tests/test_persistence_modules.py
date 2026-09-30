"""Контракт разрезанного persistence: фасад sqlite_repo + живые модули."""

from __future__ import annotations

from pathlib import Path

from request_processor.models import ClimaticTestSettings, OrganizationExtract
from request_processor.persistence import db as db_mod
from request_processor.persistence import feedback as feedback_mod
from request_processor.persistence import orgs as orgs_mod
from request_processor.persistence import settings as settings_mod
from request_processor.persistence import sqlite_repo


def test_sqlite_repo_reexports_split_modules() -> None:
    """GUI/CLI по-прежнему импортируют из sqlite_repo — это те же функции."""
    assert sqlite_repo.get_connection is db_mod.get_connection
    assert sqlite_repo.resolve_db_path is db_mod.resolve_db_path
    assert sqlite_repo.upsert_organization is orgs_mod.upsert_organization
    assert sqlite_repo.merge_organizations is orgs_mod.merge_organizations
    assert sqlite_repo.add_feedback_entry is feedback_mod.add_feedback_entry
    assert sqlite_repo.normalize_feedback_status is feedback_mod.normalize_feedback_status
    assert sqlite_repo.get_climatic_settings is settings_mod.get_climatic_settings
    assert sqlite_repo.save_climatic_settings is settings_mod.save_climatic_settings
    assert sqlite_repo.GENERATED_DIR_DEFAULT is not None


def test_orgs_module_merge_keeps_inn_card(tmp_path: Path) -> None:
    db = tmp_path / "orgs.db"
    sqlite_repo.init_db(db)
    keep = orgs_mod.create_organization(
        name="ООО НПП «Спецкабель»",
        inn="7701165130",
        db_path=db,
    )
    drop = orgs_mod.create_organization(
        name="ООО «НПП СПЕЦКАБЕЛЬ»",
        db_path=db,
    )
    assert keep != drop
    surviving = orgs_mod.merge_organizations(keep, drop, db_path=db)
    assert surviving == keep
    assert orgs_mod.get_organization_by_id(drop, db) is None
    row = orgs_mod.get_organization_by_id(keep, db)
    assert row is not None
    assert row["inn"] == "7701165130"


def test_orgs_upsert_placeholder_skipped(tmp_path: Path) -> None:
    db = tmp_path / "ph.db"
    sqlite_repo.init_db(db)
    org_id = orgs_mod.upsert_organization(
        OrganizationExtract(name="n.molchanov", role="customer"),
        db_path=db,
    )
    assert org_id == 0
    assert orgs_mod.list_organizations(db_path=db) == []


def test_feedback_module_status_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "fb.db"
    sqlite_repo.init_db(db)
    eid = feedback_mod.add_feedback_entry(
        category="ошибка",
        title="Проверка модуля",
        body="Журнал живёт отдельно от sqlite_repo.",
        db_path=db,
    )
    assert eid > 0
    assert feedback_mod.normalize_feedback_status("сделано") == "done"
    assert feedback_mod.update_feedback_status(eid, "в работе", db_path=db)
    row = feedback_mod.get_feedback_entry(eid, db)
    assert row is not None
    assert row["status"] == "in_progress"
    assert feedback_mod.feedback_status_label(row["status"]) == "в работе"


def test_settings_module_climatic_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "set.db"
    sqlite_repo.init_db(db)
    settings_mod.save_climatic_settings(
        ClimaticTestSettings(temp_low=48, humidity=120),
        db,
    )
    loaded = settings_mod.get_climatic_settings(db)
    assert loaded is not None
    assert loaded.temp_low == 48
    assert loaded.humidity == 120


def test_db_connection_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "conn.db"
    sqlite_repo.init_db(db)
    path = db_mod.resolve_db_path(db)
    assert path == db.resolve()
    with db_mod.get_connection(db) as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"]
    assert int(n) >= 0
