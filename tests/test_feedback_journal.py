"""Журнал пожеланий / обратная связь + prod-data zip."""

from __future__ import annotations

from pathlib import Path

from request_processor.persistence.sqlite_repo import (
    add_feedback_entry,
    export_feedback_journal,
    feedback_status_label,
    import_feedback_entries,
    init_db,
    list_feedback_entries,
    normalize_feedback_status,
    update_feedback_status,
)
from request_processor.training.prod_data import export_prod_data, import_prod_data


def test_add_and_list_feedback(tmp_path: Path) -> None:
    db = tmp_path / "fb.db"
    init_db(db)
    eid = add_feedback_entry(
        category="пожелание",
        section="Заявка",
        priority="обычный",
        title="Больше места под марки",
        body="Нижняя зона маленькая, хочется тянуть разделитель.",
        steps="Открыть Заявку после extract",
        db_path=db,
    )
    assert eid > 0
    rows = list_feedback_entries(db_path=db)
    assert len(rows) == 1
    assert rows[0]["title"].startswith("Больше")
    assert rows[0]["category"] == "пожелание"


def test_feedback_in_prod_data_export_import(tmp_path: Path) -> None:
    work_db = tmp_path / "work.db"
    dev_db = tmp_path / "dev.db"
    init_db(work_db)
    init_db(dev_db)
    add_feedback_entry(
        category="ошибка",
        section="КП",
        priority="высокий",
        title="КП без заказчика",
        body="После ручного ввода org имя не попало в файл.",
        expected="Имя в КП",
        actual="КП_заказчик_…",
        db_path=work_db,
    )
    zip_path = tmp_path / "prod.zip"
    result = export_prod_data(
        zip_path,
        db_path=work_db,
        corrections_dir=tmp_path / "corr_w",
        snapshots_dir=tmp_path / "snap_w",
        delta_only=False,
    )
    assert Path(result["path"]).is_file()
    assert result["manifest"]["counts"].get("feedback_entries", 0) >= 1

    imported = import_prod_data(
        zip_path,
        db_path=dev_db,
        corrections_dir=tmp_path / "corr_d",
        snapshots_dir=tmp_path / "snap_d",
        sync_db=True,
    )
    assert imported["stats"].get("feedback_imported", 0) >= 1
    rows = list_feedback_entries(db_path=dev_db)
    assert any("КП" in (r.get("title") or "") for r in rows)


def test_export_feedback_delta(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    init_db(db)
    add_feedback_entry(
        category="вопрос",
        title="Как обновить?",
        body="Куда класть zip на work?",
        db_path=db,
    )
    all_rows = export_feedback_journal(db)
    assert len(all_rows) == 1


def test_feedback_status_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "st.db"
    init_db(db)
    eid = add_feedback_entry(
        category="ошибка",
        title="Поля в окне Организации",
        body="Combobox залипает",
        db_path=db,
    )
    row = list_feedback_entries(db_path=db)[0]
    assert normalize_feedback_status(row["status"]) == "new"
    assert feedback_status_label(row["status"]) == "новое"
    assert update_feedback_status(eid, "сделано", db_path=db)
    done = list_feedback_entries(status="done", db_path=db)
    assert len(done) == 1
    assert feedback_status_label(done[0]["status"]) == "сделано"
    assert list_feedback_entries(status="новое", db_path=db) == []


def test_import_feedback_updates_status(tmp_path: Path) -> None:
    db = tmp_path / "imp.db"
    init_db(db)
    add_feedback_entry(
        category="ошибка",
        title="Combobox",
        body="залипание",
        db_path=db,
    )
    row = list_feedback_entries(db_path=db)[0]
    payload = dict(row)
    payload["status"] = "done"
    n = import_feedback_entries([payload], db_path=db)
    assert n >= 1
    again = list_feedback_entries(db_path=db)
    assert len(again) == 1
    assert normalize_feedback_status(again[0]["status"]) == "done"
