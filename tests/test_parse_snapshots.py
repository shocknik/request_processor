"""Тесты снимков парсинга и сравнения."""

from __future__ import annotations

from pathlib import Path

from request_processor.models import CableMarkMatch, OrganizationExtract, PdfExtractionResult
from request_processor.parse_compare import (
    compare_snapshots,
    compute_metrics,
    list_snapshots,
    load_snapshot,
    save_snapshot_from_extraction,
)


def _sample_result(marks: list[str], *, engine: str = "tesseract") -> PdfExtractionResult:
    return PdfExtractionResult(
        source_path="data/sample.pdf",
        source_type="pdf",
        page_count=2,
        text="периодические испытания " + " ".join(marks) * 20,
        cable_marks=[CableMarkMatch(mark=m, context=m) for m in marks],
        organizations=[
            OrganizationExtract(name="ООО «Производитель»", role="customer"),
        ],
        customer_name="ООО «Производитель»",
        manufacturer_name="",
        is_scanned=True,
        ocr_used=True,
        ocr_engine=engine,
    )


def test_save_list_load_compare(tmp_path: Path) -> None:
    a = save_snapshot_from_extraction(
        _sample_result(["FLEXICORE 100", "FLEXICORE 110 нг(A)-LS"], engine="tesseract"),
        label="A tesseract",
        ocr_dpi=300,
        snapshots_dir=tmp_path,
    )
    b = save_snapshot_from_extraction(
        _sample_result(
            ["FLEXICORE 100", "FLEXICORE 110 нг(A)-LS", "H07RN-F RU"],
            engine="easyocr",
        ),
        label="B easyocr",
        ocr_dpi=400,
        snapshots_dir=tmp_path,
    )
    listed = list_snapshots(snapshots_dir=tmp_path)
    assert len(listed) == 2

    loaded = load_snapshot(a.id, snapshots_dir=tmp_path)
    assert loaded.label == "A tesseract"
    assert loaded.metrics.marks_count == 2

    report = compare_snapshots(a, b)
    assert report["marks"]["intersection"] == 2
    assert len(report["marks"]["only_b"]) == 1
    assert report["marks"]["jaccard"] > 0.5
    assert report["quality"]["b"] >= report["quality"]["a"]


def test_compute_metrics_quality() -> None:
    empty = PdfExtractionResult(
        source_path="x.pdf",
        page_count=1,
        text="",
        cable_marks=[],
    )
    rich = _sample_result(["A 1x1", "B 2x2", "C 3x3"])
    assert compute_metrics(empty).quality_score < compute_metrics(rich).quality_score
