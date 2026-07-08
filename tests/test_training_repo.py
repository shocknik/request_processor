"""Тесты training_documents / RAG (Фаза 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from request_processor.persistence.sqlite_repo import init_db
from request_processor.persistence.training_repo import (
    add_training_label,
    import_label_file,
    index_rag_folder,
    list_training_documents,
    register_rag_document,
    register_training_document,
    resolve_document_id_for_label,
    seed_document_families,
    sync_corrections_from_dir,
)


@pytest.fixture
def training_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    init_db(db)
    return db


def test_register_training_document(training_db: Path, tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"%PDF-1.4 test")
    doc = register_training_document(sample, document_type="letter", db_path=training_db)
    assert doc["id"] >= 1
    assert doc["file_name"] == "sample.pdf"
    rows = list_training_documents(db_path=training_db)
    assert len(rows) == 1


def test_training_label_versioning(training_db: Path, tmp_path: Path) -> None:
    sample = tmp_path / "doc.docx"
    sample.write_bytes(b"docx")
    doc = register_training_document(sample, db_path=training_db)
    doc_id = int(doc["id"])
    add_training_label(doc_id, "marks", {"marks": []}, db_path=training_db)
    add_training_label(doc_id, "marks", {"marks": [{"full_mark": "ВВГ 3х2,5"}]}, db_path=training_db)
    with __import__("request_processor.persistence.sqlite_repo", fromlist=["get_connection"]).get_connection(
        training_db
    ) as conn:
        rows = conn.execute(
            "SELECT label_version, is_active FROM training_labels WHERE document_id = ? ORDER BY label_version",
            (doc_id,),
        ).fetchall()
    assert len(rows) == 2
    assert rows[-1][1] == 1


def test_sync_corrections_jsonl(training_db: Path, tmp_path: Path) -> None:
    corr = tmp_path / "corrections"
    corr.mkdir()
    (corr / "run.jsonl").write_text(
        json.dumps({"field": "customer", "original": "A", "corrected": "B", "doc": "x.pdf"})
        + "\n",
        encoding="utf-8",
    )
    stats = sync_corrections_from_dir(corr, db_path=training_db)
    assert stats["rows"] == 1


def test_seed_document_families(training_db: Path) -> None:
    count = seed_document_families(db_path=training_db)
    assert count >= 2


def test_register_rag_pmi_kind(training_db: Path, tmp_path: Path) -> None:
    pmi = tmp_path / "pmi"
    pmi.mkdir()
    doc = pmi / "ПМИ_ВВГ.docx"
    doc.write_bytes(b"docx")
    row = register_rag_document(doc, doc_kind="pmi", title="ПМИ ВВГ", db_path=training_db)
    assert row["doc_kind"] == "pmi"


def test_resolve_document_id_by_source_file(training_db: Path, tmp_path: Path) -> None:
    sample = tmp_path / "исх 163.PDF"
    sample.write_bytes(b"%PDF-1.4")
    doc = register_training_document(sample, db_path=training_db)
    payload = {"source_file": sample.name, "marks_expected": [{"mark": "ВВГ 3х2,5"}]}
    resolved = resolve_document_id_for_label(payload, tmp_path / "исх 163.json", db_path=training_db)
    assert resolved == int(doc["id"])


def test_import_label_auto_document_id(training_db: Path, tmp_path: Path) -> None:
    sample = tmp_path / "letter.pdf"
    sample.write_bytes(b"%PDF-1.4")
    doc = register_training_document(sample, db_path=training_db)
    label_path = tmp_path / "labels" / "marks" / "letter.json"
    label_path.parent.mkdir(parents=True)
    label_path.write_text(
        json.dumps(
            {
                "source_file": sample.name,
                "marks_expected": [{"mark": "ВВГнг(А) 3х2,5"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    label_id = import_label_file(None, label_path, db_path=training_db)
    assert label_id >= 1
    rows = list_training_documents(db_path=training_db)
    assert rows[0]["label_status"] == "partial"
    assert int(rows[0]["id"]) == int(doc["id"])