"""Тесты пакета данных prod (export/import между ПК)."""

from __future__ import annotations

from pathlib import Path

from request_processor.training.prod_data import (
    export_prod_data,
    get_prod_station_id,
    import_prod_data,
)
from request_processor.persistence.sqlite_repo import init_db


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "field.db"
    init_db(db)
    return db


def test_export_import_prod_data_roundtrip(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    corr = tmp_path / "corrections"
    snap = tmp_path / "snapshots"
    corr.mkdir()
    snap.mkdir()
    (corr / "20260721_test.jsonl").write_text(
        '{"field":"customer","corrected":"ООО Тест"}\n', encoding="utf-8"
    )
    (snap / "20260721_snap.json").write_text('{"id":"x","marks":[]}\n', encoding="utf-8")

    station = get_prod_station_id(db)
    assert station
    out = tmp_path / "prod_data_pack.zip"
    result = export_prod_data(
        out,
        db_path=db,
        corrections_dir=corr,
        snapshots_dir=snap,
        delta_only=False,
        operator_note="unit test",
    )
    assert Path(result["path"]).is_file()
    assert result["manifest"]["counts"]["correction_files"] == 1

    corr2 = tmp_path / "corrections_import"
    snap2 = tmp_path / "snapshots_import"
    imported = import_prod_data(
        out,
        db_path=db,
        corrections_dir=corr2,
        snapshots_dir=snap2,
        sync_db=False,
    )
    assert imported["stats"]["corrections_copied"] == 1
    assert imported["stats"]["snapshots_copied"] == 1
    assert list(corr2.glob("*.jsonl"))


def test_import_skips_duplicate_content(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    corr = tmp_path / "corrections"
    snap = tmp_path / "snapshots"
    corr.mkdir()
    snap.mkdir()
    payload = '{"field":"mark","corrected":"МКЭШ"}\n'
    (corr / "a.jsonl").write_text(payload, encoding="utf-8")

    out = tmp_path / "pack.zip"
    export_prod_data(
        out,
        db_path=db,
        corrections_dir=corr,
        snapshots_dir=snap,
        delta_only=False,
    )
    dest = tmp_path / "dest_corr"
    dest.mkdir()
    r1 = import_prod_data(
        out, db_path=db, corrections_dir=dest, snapshots_dir=tmp_path / "s1", sync_db=False
    )
    r2 = import_prod_data(
        out, db_path=db, corrections_dir=dest, snapshots_dir=tmp_path / "s2", sync_db=False
    )
    assert r1["stats"]["corrections_copied"] == 1
    assert r2["stats"]["corrections_skipped_duplicate"] >= 1
