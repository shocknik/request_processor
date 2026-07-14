"""
OCR benchmark: compare raw vs preprocessed recognition on a single page.

Reports saved to data/training/exports/reports/.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ...config import PROJECT_ROOT, TRAINING_EXPORTS_REPORTS_DIR
from ..pdf_extractor import _find_tesseract, _render_pages
from .confidence import OcrPageResult, ocr_image_with_data
from .preprocess import (
    PREPROCESS_VERSION,
    correct_orientation,
    is_cv_available,
    preprocess_for_ocr,
    preprocess_metadata,
)


def _normalize_for_cer(text: str) -> str:
    text = text.lower().replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def character_error_rate(predicted: str, ground_truth: str) -> float | None:
    """Levenshtein-based CER; None if ground truth is empty."""
    gt = _normalize_for_cer(ground_truth)
    pred = _normalize_for_cer(predicted)
    if not gt:
        return None
    if not pred:
        return 1.0

    rows = len(gt) + 1
    cols = len(pred) + 1
    dist = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dist[i][0] = i
    for j in range(cols):
        dist[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if gt[i - 1] == pred[j - 1] else 1
            dist[i][j] = min(dist[i - 1][j] + 1, dist[i][j - 1] + 1, dist[i - 1][j - 1] + cost)
    return round(dist[rows - 1][cols - 1] / len(gt), 4)


def _load_ocr_page_gt(pdf_path: Path, page: int) -> str | None:
    labels_dir = PROJECT_ROOT / "data" / "training" / "labels" / "ocr_pages"
    if not labels_dir.is_dir():
        return None
    stem = pdf_path.stem
    for candidate in labels_dir.glob(f"{stem}*.json"):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        pages = payload.get("pages") or []
        for entry in pages:
            if int(entry.get("page", 0)) == page:
                return str(entry.get("text_expected") or entry.get("text") or "")
        if payload.get("page") == page:
            return str(payload.get("text_expected") or payload.get("text") or "")
    return None


def _run_tesseract_page(
    image: Any,
    *,
    dpi: int,
    use_preprocess: bool,
    soft_preprocess: bool = False,
) -> OcrPageResult:
    import pytesseract

    tesseract_cmd = _find_tesseract()
    if not tesseract_cmd:
        raise RuntimeError("Tesseract OCR не найден")
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    working = image
    if use_preprocess:
        # soft: no adaptive threshold (better for Latin brand tables after orient)
        working = preprocess_for_ocr(
            image,
            adaptive_threshold=not soft_preprocess,
        )
    preprocess_ver = PREPROCESS_VERSION if use_preprocess and is_cv_available() else None
    return ocr_image_with_data(
        working,
        pytesseract,
        dpi=dpi,
        preprocess_version=preprocess_ver,
    )


def benchmark_pdf_page(
    pdf_path: Path | str,
    *,
    page: int = 1,
    dpi: int = 200,
) -> dict[str, Any]:
    """
    Compare OCR on one page: raw vs preprocessed after auto-orient (v3).
    """
    path = Path(pdf_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF не найден: {path}")

    images = _render_pages(path, dpi=dpi)
    if not images:
        raise ValueError(f"PDF без страниц: {path}")
    if page < 1 or page > len(images):
        raise ValueError(f"Страница {page} вне диапазона 1..{len(images)}")

    # Orientation first — without it page-2 FLEXICORE CER stays ~88% garbage
    import pytesseract

    tesseract_cmd = _find_tesseract()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    image = correct_orientation(images[page - 1], tesseract_cmd=tesseract_cmd)
    gt_text = _load_ocr_page_gt(path, page)

    t0 = time.perf_counter()
    raw_result = _run_tesseract_page(image, dpi=dpi, use_preprocess=False)
    raw_ms = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    # Soft preprocess for fair Latin+RU comparison (matches production dual path)
    pre_result = _run_tesseract_page(
        image, dpi=dpi, use_preprocess=True, soft_preprocess=True
    )
    pre_ms = int((time.perf_counter() - t1) * 1000)

    # Mark-column / ROI: left-center band where brand names usually sit (35s metric)
    t2 = time.perf_counter()
    mark_col = _ocr_mark_column_roi(image, dpi=dpi)
    mark_col_ms = int((time.perf_counter() - t2) * 1000)
    mark_gt = _extract_mark_lines_from_gt(gt_text) if gt_text else None

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(path.relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
        if path.is_relative_to(PROJECT_ROOT.resolve())
        else path.as_posix(),
        "page": page,
        "page_count": len(images),
        "dpi": dpi,
        "auto_orient": True,
        "preprocess": preprocess_metadata(),
        "variants": {
            "raw": {
                "text_chars": len(raw_result.text),
                "word_count": len(raw_result.words),
                "mean_confidence": raw_result.mean_confidence,
                "duration_ms": raw_ms,
                "cer": character_error_rate(raw_result.text, gt_text) if gt_text else None,
                "text_preview": raw_result.text[:500],
            },
            "preprocessed": {
                "text_chars": len(pre_result.text),
                "word_count": len(pre_result.words),
                "mean_confidence": pre_result.mean_confidence,
                "duration_ms": pre_ms,
                "cer": character_error_rate(pre_result.text, gt_text) if gt_text else None,
                "text_preview": pre_result.text[:500],
            },
            "mark_column_roi": {
                "text_chars": len(mark_col.get("text") or ""),
                "duration_ms": mark_col_ms,
                "cer": character_error_rate(mark_col.get("text") or "", mark_gt)
                if mark_gt
                else character_error_rate(mark_col.get("text") or "", gt_text)
                if gt_text
                else None,
                "roi": mark_col.get("roi"),
                "text_preview": (mark_col.get("text") or "")[:500],
            },
        },
        "ground_truth_available": gt_text is not None,
        "mark_column_gt_available": mark_gt is not None,
    }

    if gt_text:
        report["ground_truth_chars"] = len(gt_text)

    raw_cer = report["variants"]["raw"]["cer"]
    pre_cer = report["variants"]["preprocessed"]["cer"]
    if raw_cer is not None and pre_cer is not None:
        report["cer_delta"] = round(pre_cer - raw_cer, 4)
        report["preprocess_improved_cer"] = pre_cer < raw_cer

    return report


def _extract_mark_lines_from_gt(gt_text: str) -> str:
    """Keep GT lines that look like brand/mark rows for mark-column CER."""
    lines = []
    for line in gt_text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(
            r"FLEXICORE|H07RN|VicabFLEX|нг\(|кВ|UTP|Cat\s*5|[А-ЯЁ]{2,}\s*\d",
            s,
            re.IGNORECASE,
        ):
            lines.append(s)
    return "\n".join(lines) if lines else gt_text


def _ocr_mark_column_roi(image: Any, *, dpi: int) -> dict[str, Any]:
    """OCR left-center horizontal band (typical mark column in application tables)."""
    import pytesseract

    tesseract_cmd = _find_tesseract()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    w, h = image.size
    # Column ~15–55% width (after # col); full height of table body ~20–90%
    x0, x1 = int(w * 0.12), int(w * 0.58)
    y0, y1 = int(h * 0.15), int(h * 0.95)
    crop = image.crop((x0, y0, x1, y1))
    config = "--psm 6 --oem 1"
    try:
        text = pytesseract.image_to_string(crop, lang="eng+rus", config=config) or ""
    except Exception:
        text = pytesseract.image_to_string(crop, lang="eng", config=config) or ""
    return {
        "text": text,
        "roi": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "dpi": dpi},
    }


def save_benchmark_report(report: dict[str, Any], output_path: Path | None = None) -> Path:
    if output_path is None:
        stem = Path(str(report.get("source_file", "ocr"))).stem
        page = report.get("page", 1)
        date = datetime.now().date().isoformat()
        output_path = TRAINING_EXPORTS_REPORTS_DIR / f"ocr_benchmark_{stem}_p{page}_{date}.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def benchmark_scans_batch(
    pdf_paths: list[Path | str],
    *,
    page: int = 1,
    dpi: int = 200,
) -> dict[str, Any]:
    """Run benchmark on multiple scan PDFs; aggregate summary."""
    per_file: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for item in pdf_paths:
        path = Path(item)
        try:
            row = benchmark_pdf_page(path, page=page, dpi=dpi)
            per_file.append(row)
        except Exception as exc:
            errors.append({"file": path.name, "error": str(exc)})

    improved = sum(
        1
        for r in per_file
        if r.get("preprocess_improved_cer") is True
        or (
            r.get("preprocess_improved_cer") is None
            and (r["variants"]["preprocessed"]["mean_confidence"] or 0)
            > (r["variants"]["raw"]["mean_confidence"] or 0)
        )
    )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "page": page,
        "dpi": dpi,
        "files_total": len(pdf_paths),
        "files_ok": len(per_file),
        "files_error": len(errors),
        "preprocess_improved_count": improved,
        "per_file": per_file,
        "errors": errors,
    }