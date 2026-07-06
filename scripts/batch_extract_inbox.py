"""
Пакетный прогон extract-pdf --dry-run --validate на файлах из inbox.

Фаза 0 мастер-плана (35): «ожидание vs факт» для обучающего корпуса.
См. Obsidian: 35e §8, 35h — Прогон inbox (фаза 0).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from request_processor.extraction.pdf_extractor import extract_from_document
from request_processor.validation.extraction_validator import validate_extraction

INBOX = ROOT / "data" / "training" / "documents" / "inbox"
REPORTS = ROOT / "data" / "training" / "exports" / "reports"
SUPPORTED = {".pdf", ".docx"}


def _safe_stem(path: Path) -> str:
    stem = path.stem.strip()
    return stem.replace(" ", "_").replace("№", "N")


def process_file(path: Path) -> dict:
    result = extract_from_document(path, use_ocr=True, use_ocr_cache=False)
    report = validate_extraction(result)

    out_json = REPORTS / f"{_safe_stem(path)}_run1.json"
    out_json.write_text(result.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

    marks = [m.mark for m in result.cable_marks]
    return {
        "file": path.name,
        "format": path.suffix.lower().lstrip("."),
        "source_type": result.source_type,
        "pages": result.page_count,
        "chars": len(result.text),
        "tables": len(result.tables),
        "marks_count": len(marks),
        "marks": marks[:5],
        "customer": result.customer_name,
        "manufacturer": result.manufacturer_name,
        "document_type": report.document_type,
        "confidence": round(report.overall_confidence, 2),
        "status": report.overall_status.value,
        "ocr_used": result.ocr_used,
        "is_scanned": result.is_scanned,
        "json": str(out_json.relative_to(ROOT)).replace("\\", "/"),
        "error": None,
    }


def main() -> int:
    if not INBOX.is_dir():
        print(f"inbox not found: {INBOX}", file=sys.stderr)
        return 1

    REPORTS.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED
    )
    skipped = sorted(
        p.name for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() not in SUPPORTED
    )

    rows: list[dict] = []
    errors: list[dict] = []

    print(f"Processing {len(files)} files from {INBOX}")
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name} …", flush=True)
        try:
            row = process_file(path)
            rows.append(row)
            print(
                f"  OK: type={row['document_type']} marks={row['marks_count']} "
                f"conf={row['confidence']:.0%} status={row['status']}"
            )
        except Exception as exc:
            err = {"file": path.name, "error": str(exc)}
            errors.append(err)
            print(f"  FAIL: {exc}", file=sys.stderr)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inbox": str(INBOX.relative_to(ROOT)).replace("\\", "/"),
        "processed": len(rows),
        "failed": len(errors),
        "skipped_extensions": skipped,
        "results": rows,
        "errors": errors,
    }
    summary_path = REPORTS / "inbox_batch_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSummary: {summary_path}")
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())