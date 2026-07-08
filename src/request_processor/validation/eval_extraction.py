"""
Сравнение извлечённых марок с эталонной разметкой оператора (ground truth).

См. Obsidian 35m — eval-extraction, 35c §5.1.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, TRAINING_LABELS_MARKS_DIR
from ..extraction.pdf_extractor import extract_from_document, find_cable_marks
from ..persistence.training_repo import get_training_document_by_path


def normalize_mark_for_eval(mark: str) -> str:
    text = mark.lower().replace("х", "x").replace("×", "x")
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    return re.sub(r"\s+", "", text)


def _expected_marks_from_payload(payload: dict[str, Any]) -> list[str]:
    marks: list[str] = []
    for item in payload.get("marks_expected") or []:
        if isinstance(item, dict):
            val = item.get("mark") or item.get("full_mark")
            if val:
                marks.append(str(val))
        elif isinstance(item, str):
            marks.append(item)
    for item in payload.get("marks") or []:
        if isinstance(item, dict):
            val = item.get("full_mark") or item.get("mark")
            if val:
                marks.append(str(val))
        elif isinstance(item, str):
            marks.append(item)
    return marks


def _resolve_doc_path(payload: dict[str, Any], label_path: Path) -> Path | None:
    source = payload.get("source_file")
    if source:
        candidate = Path(str(source))
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.is_file():
            return candidate.resolve()
        by_name = PROJECT_ROOT / "data" / "training" / "documents" / "registered" / Path(source).name
        if by_name.is_file():
            return by_name.resolve()

    stem = label_path.stem
    registered = PROJECT_ROOT / "data" / "training" / "documents" / "registered"
    if registered.is_dir():
        for suffix in (".pdf", ".PDF", ".docx", ".DOCX", ".doc", ".DOC"):
            candidate = registered / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate.resolve()
    return None


def _predicted_marks(doc_path: Path, *, use_ocr_cache: bool = True) -> list[str]:
    extraction = extract_from_document(
        doc_path,
        use_ocr=True,
        use_ocr_cache=use_ocr_cache,
    )
    if extraction.tables:
        from ..extraction.pdf_extractor import _resolve_cable_marks

        matches = _resolve_cable_marks(extraction.text, extraction.tables)
    else:
        matches = find_cable_marks(extraction.text)
    return [m.mark for m in matches]


def eval_single_label_file(
    label_path: Path,
    *,
    use_ocr_cache: bool = True,
    db_path: str | Path = "data/app.db",
) -> dict[str, Any] | None:
    payload = json.loads(label_path.read_text(encoding="utf-8"))
    expected = _expected_marks_from_payload(payload)
    if not expected:
        return None

    doc_path = _resolve_doc_path(payload, label_path)
    if doc_path is None:
        return {
            "label_file": label_path.name,
            "status": "skipped",
            "reason": "source_file не найден",
            "expected_count": len(expected),
        }

    doc_row = get_training_document_by_path(doc_path, db_path=db_path)
    predicted = _predicted_marks(doc_path, use_ocr_cache=use_ocr_cache)
    expected_norm = {normalize_mark_for_eval(m) for m in expected}
    predicted_norm = {normalize_mark_for_eval(m) for m in predicted}
    matched = expected_norm & predicted_norm
    missed = expected_norm - predicted_norm
    extra = predicted_norm - expected_norm
    recall = len(matched) / len(expected_norm) if expected_norm else 0.0
    precision = len(matched) / len(predicted_norm) if predicted_norm else 0.0

    return {
        "label_file": label_path.name,
        "document_id": doc_row["id"] if doc_row else None,
        "source_file": str(doc_path.relative_to(PROJECT_ROOT.resolve())).replace("\\", "/")
        if doc_path.is_relative_to(PROJECT_ROOT.resolve())
        else doc_path.as_posix(),
        "status": "ok",
        "expected": sorted(expected),
        "predicted": sorted(predicted),
        "matched": len(matched),
        "missed": sorted(missed),
        "extra": sorted(extra),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
    }


def eval_marks_labels_dir(
    labels_dir: Path | str | None = None,
    *,
    use_ocr_cache: bool = True,
    db_path: str | Path = "data/app.db",
) -> dict[str, Any]:
    root = Path(labels_dir or TRAINING_LABELS_MARKS_DIR)
    files = sorted(
        p for p in root.glob("*.json") if root.is_dir() and not p.name.startswith("_")
    ) if root.is_dir() else []
    per_file: list[dict[str, Any]] = []
    skipped = 0
    for path in files:
        row = eval_single_label_file(path, use_ocr_cache=use_ocr_cache, db_path=db_path)
        if row is None:
            skipped += 1
            continue
        if row.get("status") == "skipped":
            skipped += 1
        per_file.append(row)

    evaluated = [r for r in per_file if r.get("status") == "ok"]
    total_expected = sum(len(r.get("expected") or []) for r in evaluated)
    total_matched = sum(int(r.get("matched") or 0) for r in evaluated)
    macro_recall = (
        sum(float(r.get("recall") or 0) for r in evaluated) / len(evaluated) if evaluated else 0.0
    )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "labels_dir": str(root),
        "files_total": len(files),
        "files_evaluated": len(evaluated),
        "files_skipped": skipped,
        "marks_expected_total": total_expected,
        "marks_matched_total": total_matched,
        "macro_recall": round(macro_recall, 4),
        "micro_recall": round(total_matched / total_expected, 4) if total_expected else 0.0,
        "per_file": per_file,
    }