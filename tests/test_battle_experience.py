"""Тесты пакета боевого опыта (export/import между ПК)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from request_processor.persistence.sqlite_repo import init_db
from request_processor.training.battle_experience import (
    export_battle_experience,
    get_battle_host_id,
    import_battle_experience,
)


def test_export_import_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "battle.db"
    init_db(db)

    corr = tmp_path / "corrections"
    corr.mkdir()
    (corr / "fix1.jsonl").write_text(
        json.dumps({"field": "mark", "original": "A", "corrected": "B", "doc": "x.pdf"})
        + "\n",
        encoding="utf-8",
    )
    snaps = tmp_path / "snapshots"
    snaps.mkdir()
    (snaps / "snap1.json").write_text(
        json.dumps({"id": "s1", "marks": ["ВВГ 3х2,5"]}),
        encoding="utf-8",
    )

    host = get_battle_host_id(db)
    assert host

    archive = tmp_path / "pack.zip"
    out = export_battle_experience(
        archive,
        db_path=db,
        corrections_dir=corr,
        snapshots_dir=snaps,
        delta_only=False,
        operator_note="smoke test",
    )
    assert archive.is_file()
    assert out["manifest"]["counts"]["correction_files"] == 1

    dev_corr = tmp_path / "dev" / "corrections"
    dev_snaps = tmp_path / "dev" / "snapshots"
    dev_db = tmp_path / "dev.db"
    init_db(dev_db)

    result = import_battle_experience(
        archive,
        db_path=dev_db,
        corrections_dir=dev_corr,
        snapshots_dir=dev_snaps,
    )
    assert result["stats"]["corrections_copied"] == 1
    assert result["stats"]["snapshots_copied"] == 1
    assert list(dev_corr.glob(f"{host}_*.jsonl"))

    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["operator_note"] == "smoke test"
    assert manifest["format_version"] == 1


def test_import_skips_duplicate_content(tmp_path: Path) -> None:
    db = tmp_path / "d.db"
    init_db(db)
    corr = tmp_path / "corrections"
    corr.mkdir()
    line = json.dumps({"field": "mark", "original": "X", "corrected": "Y"})
    (corr / "a.jsonl").write_text(line + "\n", encoding="utf-8")

    archive = tmp_path / "p.zip"
    export_battle_experience(
        archive,
        db_path=db,
        corrections_dir=corr,
        snapshots_dir=tmp_path / "empty_snaps",
        delta_only=False,
    )

    dest = tmp_path / "dest_corr"
    dest.mkdir()
    (dest / "already.jsonl").write_text(line + "\n", encoding="utf-8")

    r1 = import_battle_experience(
        archive,
        db_path=db,
        corrections_dir=dest,
        snapshots_dir=tmp_path / "dest_snaps",
        sync_db=False,
    )
    assert r1["stats"]["corrections_skipped_duplicate"] == 1
    assert r1["stats"]["corrections_copied"] == 0