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


def test_ocr_twins_cannot_score_perfect() -> None:
    """Снимок 23.09 получил 1.0 при НЕ и тройном КСБ. Так больше нельзя."""
    clean_marks = [
        CableMarkMatch(
            mark=f"СПЕЦЛАН F/UTP нг(А)-HF 4x2x0,{50 + i}",
            context="x",
            document="ТУ 16.К99-058-2014",
        )
        for i in range(7)
    ]
    base = PdfExtractionResult(
        source_path="data/sample.pdf",
        source_type="pdf",
        page_count=2,
        text="периодические испытания " * 80,
        cable_marks=clean_marks,
        organizations=[
            OrganizationExtract(name=f"ООО {i}", role="customer") for i in range(4)
        ],
        customer_name="ООО 0",
        manufacturer_name="ООО НПП «Спецкабель»",
        tables=[[["a"]]],
        is_scanned=True,
        ocr_used=True,
        ocr_engine="tesseract",
    )
    dirty = base.model_copy(
        update={
            "cable_marks": [
                *clean_marks,
                CableMarkMatch(
                    mark="СПЕЦЛАН F/UTP нг(А)-НЕ 4x2x0,52",
                    context="x",
                    document="ТУ 16.К99-058-2014",
                ),
            ]
        }
    )
    assert compute_metrics(base).quality_score == 1.0
    assert compute_metrics(dirty).quality_score <= 0.85
