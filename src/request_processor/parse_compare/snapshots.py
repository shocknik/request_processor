"""
Снимки парсинга: сохранение, метрики, сравнение A/B.

Каталог: data/parse_snapshots/
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..config import PARSE_SNAPSHOTS_DIR
from ..models import PdfExtractionResult
from ..validation.eval_extraction import normalize_mark_for_eval


class SnapshotMetrics(BaseModel):
    """Метрики одного снимка парсинга."""

    marks_count: int = 0
    orgs_count: int = 0
    text_chars: int = 0
    tables_count: int = 0
    page_count: int = 0
    ocr_used: bool = False
    ocr_engine: str | None = None
    customer_set: bool = False
    manufacturer_set: bool = False
    unique_marks: int = 0
    marks_with_document: int = 0
    # эвристика «качества» 0..1 (не GT)
    quality_score: float = 0.0


class ParseSnapshot(BaseModel):
    """Снимок одного прогона извлечения."""

    id: str
    created_at: str
    label: str = ""
    source_path: str = ""
    source_name: str = ""
    ocr_engine: str | None = None
    ocr_dpi: int | None = None
    notes: str = ""
    metrics: SnapshotMetrics = Field(default_factory=SnapshotMetrics)
    result: dict[str, Any] = Field(default_factory=dict)
    marks: list[str] = Field(default_factory=list)
    organizations: list[dict[str, Any]] = Field(default_factory=list)


def compute_metrics(result: PdfExtractionResult) -> SnapshotMetrics:
    marks = [m.mark for m in result.cable_marks]
    unique = {normalize_mark_for_eval(m) for m in marks}
    with_doc = sum(1 for m in result.cable_marks if (m.document or "").strip())
    text_len = len(result.text or "")
    # Heuristic quality: more structured marks + orgs + not-empty text
    score = 0.0
    if text_len > 100:
        score += 0.2
    if text_len > 1000:
        score += 0.1
    if marks:
        score += min(0.35, 0.05 * len(unique))
    if with_doc:
        score += min(0.15, 0.03 * with_doc)
    if result.customer_name:
        score += 0.1
    if result.manufacturer_name:
        score += 0.05
    if result.organizations:
        score += min(0.1, 0.03 * len(result.organizations))
    if result.tables:
        score += 0.05
    score = round(min(1.0, score), 3)

    return SnapshotMetrics(
        marks_count=len(marks),
        orgs_count=len(result.organizations),
        text_chars=text_len,
        tables_count=len(result.tables),
        page_count=result.page_count,
        ocr_used=result.ocr_used,
        ocr_engine=result.ocr_engine,
        customer_set=bool(result.customer_name),
        manufacturer_set=bool(result.manufacturer_name),
        unique_marks=len(unique),
        marks_with_document=with_doc,
        quality_score=score,
    )


def save_snapshot_from_extraction(
    result: PdfExtractionResult,
    *,
    label: str = "",
    notes: str = "",
    ocr_dpi: int | None = None,
    snapshots_dir: Path | None = None,
) -> ParseSnapshot:
    root = Path(snapshots_dir or PARSE_SNAPSHOTS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    sid = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    source = Path(result.source_path) if result.source_path else Path("unknown")
    metrics = compute_metrics(result)
    snap = ParseSnapshot(
        id=sid,
        created_at=datetime.now().isoformat(timespec="seconds"),
        label=label or f"{source.stem} · {result.ocr_engine or 'no-ocr'}",
        source_path=str(result.source_path),
        source_name=source.name,
        ocr_engine=result.ocr_engine,
        ocr_dpi=ocr_dpi,
        notes=notes,
        metrics=metrics,
        result=json.loads(result.model_dump_json()),
        marks=[m.mark for m in result.cable_marks],
        organizations=[
            {
                "role": o.role,
                "name": o.name,
                "inn": o.inn,
                "address": o.address or o.legal_address,
            }
            for o in result.organizations
        ],
    )
    path = root / f"{sid}.json"
    path.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    return snap


def load_snapshot(path_or_id: str | Path, *, snapshots_dir: Path | None = None) -> ParseSnapshot:
    root = Path(snapshots_dir or PARSE_SNAPSHOTS_DIR)
    p = Path(path_or_id)
    if not p.is_file():
        cand = root / f"{path_or_id}.json"
        if cand.is_file():
            p = cand
        else:
            matches = list(root.glob(f"*{path_or_id}*.json"))
            if not matches:
                raise FileNotFoundError(f"Снимок не найден: {path_or_id}")
            p = matches[0]
    return ParseSnapshot.model_validate_json(p.read_text(encoding="utf-8"))


def list_snapshots(*, snapshots_dir: Path | None = None, limit: int = 200) -> list[dict[str, Any]]:
    root = Path(snapshots_dir or PARSE_SNAPSHOTS_DIR)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            metrics = data.get("metrics") or {}
            items.append(
                {
                    "id": data.get("id") or path.stem,
                    "path": str(path),
                    "created_at": data.get("created_at") or "",
                    "label": data.get("label") or "",
                    "source_name": data.get("source_name") or "",
                    "ocr_engine": data.get("ocr_engine"),
                    "ocr_dpi": data.get("ocr_dpi"),
                    "marks_count": metrics.get("marks_count", 0),
                    "quality_score": metrics.get("quality_score", 0),
                    "text_chars": metrics.get("text_chars", 0),
                }
            )
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items


def compare_snapshots(a: ParseSnapshot, b: ParseSnapshot) -> dict[str, Any]:
    """Сравнение двух снимков: пересечение марок, org, метрики."""
    marks_a = {normalize_mark_for_eval(m) for m in a.marks}
    marks_b = {normalize_mark_for_eval(m) for m in b.marks}
    only_a = sorted(marks_a - marks_b)
    only_b = sorted(marks_b - marks_a)
    both = sorted(marks_a & marks_b)

    def _org_key(o: dict[str, Any]) -> str:
        return re.sub(r"\s+", " ", f"{o.get('role','')}|{o.get('name','')}".lower()).strip()

    orgs_a = {_org_key(o) for o in a.organizations}
    orgs_b = {_org_key(o) for o in b.organizations}

    ma, mb = a.metrics, b.metrics
    jaccard = len(both) / len(marks_a | marks_b) if (marks_a or marks_b) else 1.0

    return {
        "snapshot_a": {"id": a.id, "label": a.label, "ocr_engine": a.ocr_engine, "dpi": a.ocr_dpi},
        "snapshot_b": {"id": b.id, "label": b.label, "ocr_engine": b.ocr_engine, "dpi": b.ocr_dpi},
        "marks": {
            "count_a": len(a.marks),
            "count_b": len(b.marks),
            "unique_a": len(marks_a),
            "unique_b": len(marks_b),
            "intersection": len(both),
            "only_a": only_a,
            "only_b": only_b,
            "both": both,
            "jaccard": round(jaccard, 4),
            "recall_a_vs_b": round(len(both) / len(marks_b), 4) if marks_b else None,
            "recall_b_vs_a": round(len(both) / len(marks_a), 4) if marks_a else None,
        },
        "organizations": {
            "count_a": len(a.organizations),
            "count_b": len(b.organizations),
            "only_a": sorted(orgs_a - orgs_b),
            "only_b": sorted(orgs_b - orgs_a),
            "both": sorted(orgs_a & orgs_b),
        },
        "metrics_delta": {
            "marks_count": mb.marks_count - ma.marks_count,
            "text_chars": mb.text_chars - ma.text_chars,
            "quality_score": round(mb.quality_score - ma.quality_score, 3),
            "orgs_count": mb.orgs_count - ma.orgs_count,
            "tables_count": mb.tables_count - ma.tables_count,
        },
        "quality": {
            "a": ma.quality_score,
            "b": mb.quality_score,
            "winner": "B"
            if mb.quality_score > ma.quality_score + 0.02
            else ("A" if ma.quality_score > mb.quality_score + 0.02 else "tie"),
        },
    }
