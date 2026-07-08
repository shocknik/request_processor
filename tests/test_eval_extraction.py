"""Тесты eval-extraction (сравнение марок с эталоном)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from request_processor.persistence.sqlite_repo import init_db
from request_processor.persistence.training_repo import register_training_document
from request_processor.validation.eval_extraction import (
    eval_marks_labels_dir,
    normalize_mark_for_eval,
)


def test_normalize_mark_for_eval() -> None:
    assert normalize_mark_for_eval("ВВГ 3х2,5") == normalize_mark_for_eval("ввг 3x2,5")
    assert normalize_mark_for_eval("24x0,5") == normalize_mark_for_eval("24x0.5")


def test_eval_marks_labels_dir_empty(tmp_path: Path) -> None:
    labels = tmp_path / "marks"
    labels.mkdir()
    report = eval_marks_labels_dir(labels)
    assert report["files_total"] == 0
    assert report["micro_recall"] == 0.0


def test_eval_marks_labels_dir_with_mock_extraction(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    init_db(db)
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")
    register_training_document(doc, db_path=db)

    labels = tmp_path / "marks"
    labels.mkdir()
    (labels / "sample.json").write_text(
        json.dumps(
            {
                "source_file": str(doc),
                "marks_expected": [
                    {"mark": "ВВГнг(А) 3х2,5"},
                    {"mark": "ПВСнг(А)-LS 3х2,5"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch(
        "request_processor.validation.eval_extraction._predicted_marks",
        return_value=["ВВГнг(А) 3х2,5", "лишняя марка"],
    ):
        report = eval_marks_labels_dir(labels, db_path=db)

    assert report["files_evaluated"] == 1
    assert report["micro_recall"] == 0.5
    row = report["per_file"][0]
    assert row["matched"] == 1
    assert "пвснг" in "".join(row["missed"])