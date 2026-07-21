"""S2.5: демо 3 OCR-марок (MarkCorrector, без обязательного LLM)."""

from __future__ import annotations

from pathlib import Path

from request_processor.assistant.demo_marks import (
    DEMO_OCR_CASES,
    format_demo_table,
    run_ocr_marks_demo,
    save_demo_report,
)
from request_processor.persistence.sqlite_repo import init_db


def test_demo_ocr_marks_three_cases(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    init_db(db)
    report = run_ocr_marks_demo(db_path=db, record_feedback=True)
    assert report["counts"]["total"] == 3
    assert len(report["rows"]) == 3
    # Хотя бы 2 кейса должны улучшиться детерминированным слоем
    improved = sum(
        1
        for r in report["rows"]
        if r["changed"] and r["helped"] in ("yes", "partial")
    )
    assert improved >= 2, report
    table = format_demo_table(report)
    assert "S2.5" in table
    path = save_demo_report(report, output_dir=tmp_path / "reports")
    assert path.is_file()
    assert "s2_5_ocr_demo_" in path.name


def test_demo_cases_ids_unique() -> None:
    ids = [c["id"] for c in DEMO_OCR_CASES]
    assert len(ids) == len(set(ids)) == 3
