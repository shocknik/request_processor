"""
CRUD для обучающих данных: training_documents, labels, RAG, corrections.

См. Obsidian: 35c — БД и файловое хранилище для обучения.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ..config import (
    EXTRACTED_DIR,
    FAMILIES_DIR,
    PROJECT_ROOT,
    RAG_CORPUS_DIR,
    TRAINING_CORRECTIONS_DIR,
    TRAINING_INBOX,
    TRAINING_REGISTERED,
)
from ..extraction.pdf_extractor import extract_from_document
from ..models import PdfExtractionResult
from ..validation.extraction_validator import detect_document_type, validate_extraction
from .sqlite_repo import get_connection, resolve_db_path

LabelType = Literal["marks", "organizations", "requirements", "ocr_page", "full_json"]
RagDocKind = Literal["tu", "protocol", "gost", "method", "pmi", "internal", "template", "faq"]

RAG_FOLDER_KINDS: dict[str, RagDocKind] = {
    "tu": "tu",
    "protocols": "protocol",
    "gost": "gost",
    "internal": "internal",
    "pmi": "pmi",
}

SUPPORTED_DOC_SUFFIXES = {".pdf", ".docx", ".doc", ".PDF", ".DOCX", ".DOC"}
RAG_SUFFIXES = SUPPORTED_DOC_SUFFIXES | {".txt", ".md", ".json"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _rel_path(path: Path | str) -> str:
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def register_training_document(
    file_path: Path | str,
    *,
    document_type: str | None = None,
    document_family: str | None = None,
    source: str = "operator",
    label_status: str = "unlabeled",
    notes: str | None = None,
    page_count: int | None = None,
    db_path: str | Path = "data/app.db",
) -> dict[str, Any]:
    """Регистрирует или обновляет запись в training_documents."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")

    rel = _rel_path(path)
    file_hash = file_sha256(path)
    now = _now()

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM training_documents WHERE file_path = ? OR file_hash = ?",
            (rel, file_hash),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE training_documents SET
                    file_path = ?, file_hash = ?, file_name = ?, mime_type = ?,
                    page_count = COALESCE(?, page_count),
                    document_type = COALESCE(?, document_type),
                    document_family = COALESCE(?, document_family),
                    source = ?, label_status = ?, notes = COALESCE(?, notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    rel,
                    file_hash,
                    path.name,
                    _mime_type(path),
                    page_count,
                    document_type,
                    document_family,
                    source,
                    label_status,
                    notes,
                    now,
                    existing[0],
                ),
            )
            doc_id = int(existing[0])
        else:
            cur = conn.execute(
                """
                INSERT INTO training_documents (
                    file_path, file_hash, file_name, mime_type, page_count,
                    document_type, document_family, source, label_status, notes,
                    registered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rel,
                    file_hash,
                    path.name,
                    _mime_type(path),
                    page_count,
                    document_type,
                    document_family,
                    source,
                    label_status,
                    notes,
                    now,
                    now,
                ),
            )
            doc_id = int(cur.lastrowid)

    row = get_training_document(doc_id, db_path=db_path)
    assert row is not None
    return row


def get_training_document(doc_id: int, *, db_path: str | Path = "data/app.db") -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM training_documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def get_training_document_by_path(
    file_path: Path | str,
    *,
    db_path: str | Path = "data/app.db",
) -> dict[str, Any] | None:
    rel = _rel_path(file_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM training_documents WHERE file_path = ?",
            (rel,),
        ).fetchone()
    return dict(row) if row else None


def list_training_documents(
    *,
    label_status: str | None = None,
    document_type: str | None = None,
    limit: int = 200,
    db_path: str | Path = "data/app.db",
) -> list[dict[str, Any]]:
    query = "SELECT * FROM training_documents WHERE 1=1"
    params: list[Any] = []
    if label_status:
        query += " AND label_status = ?"
        params.append(label_status)
    if document_type:
        query += " AND document_type = ?"
        params.append(document_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def add_training_label(
    document_id: int,
    label_type: LabelType,
    payload: dict[str, Any] | list[Any],
    *,
    labeled_by: str = "operator",
    db_path: str | Path = "data/app.db",
) -> int:
    """Добавляет версию разметки; предыдущие active=0 для того же label_type."""
    now = _now()
    payload_json = json.dumps(payload, ensure_ascii=False)
    with get_connection(db_path) as conn:
        version_row = conn.execute(
            """
            SELECT COALESCE(MAX(label_version), 0) FROM training_labels
            WHERE document_id = ? AND label_type = ?
            """,
            (document_id, label_type),
        ).fetchone()
        version = int(version_row[0]) + 1
        conn.execute(
            """
            UPDATE training_labels SET is_active = 0
            WHERE document_id = ? AND label_type = ?
            """,
            (document_id, label_type),
        )
        cur = conn.execute(
            """
            INSERT INTO training_labels (
                document_id, label_type, label_version, payload_json,
                labeled_by, created_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (document_id, label_type, version, payload_json, labeled_by, now),
        )
        return int(cur.lastrowid)


def resolve_document_id_for_label(
    payload: dict[str, Any],
    label_file: Path | str,
    *,
    db_path: str | Path = "data/app.db",
) -> int | None:
    """Находит training_documents.id по полям JSON или имени файла разметки."""
    raw_id = payload.get("document_id")
    if isinstance(raw_id, int):
        row = get_training_document(raw_id, db_path=db_path)
        if row:
            return raw_id
    if isinstance(raw_id, str) and raw_id.isdigit():
        doc_id = int(raw_id)
        if get_training_document(doc_id, db_path=db_path):
            return doc_id

    candidates: list[str] = []
    source = payload.get("source_file")
    if source:
        candidates.append(Path(str(source)).name)
        candidates.append(_rel_path(PROJECT_ROOT / source if not Path(str(source)).is_absolute() else source))
    path = Path(label_file)
    candidates.append(path.stem)
    candidates.append(path.name)

    with get_connection(db_path) as conn:
        for name in candidates:
            if not name:
                continue
            found = conn.execute(
                "SELECT id FROM training_documents WHERE file_name = ? ORDER BY id DESC LIMIT 1",
                (Path(name).name,),
            ).fetchone()
            if found:
                return int(found[0])
            found = conn.execute(
                "SELECT id FROM training_documents WHERE file_path LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{Path(name).name}",),
            ).fetchone()
            if found:
                return int(found[0])
    return None


def import_label_file(
    document_id: int | None,
    label_file: Path | str,
    *,
    label_type: LabelType | None = None,
    db_path: str | Path = "data/app.db",
) -> int:
    path = Path(label_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    doc_id = document_id
    if doc_id is None:
        doc_id = resolve_document_id_for_label(payload, path, db_path=db_path)
    if doc_id is None:
        raise ValueError(
            "Не найден training_documents.id: укажите --document-id или поле source_file в JSON"
        )

    inferred = label_type
    if inferred is None:
        parent = path.parent.name
        if parent in ("marks", "organizations", "requirements", "ocr_pages"):
            inferred = "ocr_page" if parent == "ocr_pages" else parent  # type: ignore[assignment]
        else:
            inferred = "full_json"
    label_id = add_training_label(doc_id, inferred, payload, db_path=db_path)
    marks = payload.get("marks_expected") or payload.get("marks") or []
    new_status = "complete" if marks else "partial"
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE training_documents SET label_status = ?, updated_at = ? WHERE id = ?",
            (new_status, _now(), doc_id),
        )
    return label_id


def record_ocr_run(
    *,
    document_id: int | None,
    source_path: str,
    engine: str,
    dpi: int | None = None,
    page_count: int | None = None,
    duration_ms: int | None = None,
    cache_path: str | None = None,
    db_path: str | Path = "data/app.db",
) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ocr_runs (
                document_id, source_path, engine, dpi, page_count,
                duration_ms, cache_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, source_path, engine, dpi, page_count, duration_ms, cache_path, _now()),
        )
        return int(cur.lastrowid)


def ingest_training_document(
    file_path: Path | str,
    *,
    document_type: str | None = None,
    document_family: str | None = None,
    move_to_registered: bool = True,
    run_extract: bool = True,
    db_path: str | Path = "data/app.db",
) -> dict[str, Any]:
    """
    Регистрирует документ, опционально извлекает метаданные, переносит в registered/.
    """
    path = Path(file_path).resolve()
    if path.suffix.lower() not in {s.lower() for s in SUPPORTED_DOC_SUFFIXES}:
        raise ValueError(f"Неподдерживаемый формат: {path.suffix}")

    extraction: PdfExtractionResult | None = None
    if run_extract:
        extraction = extract_from_document(path, use_ocr=True, use_ocr_cache=False)
        report = validate_extraction(extraction)
        document_type = document_type or report.document_type
        if document_family is None:
            try:
                from ..extraction.families.registry import get_family_registry

                family = get_family_registry().detect_best(extraction.text)
                if family:
                    document_family = family.id
            except Exception:
                pass

    dest = path
    if move_to_registered and TRAINING_INBOX.resolve() in path.parents:
        TRAINING_REGISTERED.mkdir(parents=True, exist_ok=True)
        dest = TRAINING_REGISTERED / path.name
        if dest.resolve() != path.resolve():
            shutil.move(str(path), str(dest))

    doc = register_training_document(
        dest,
        document_type=document_type,
        document_family=document_family,
        page_count=extraction.page_count if extraction else None,
        db_path=db_path,
    )

    if extraction:
        payload = json.loads(extraction.model_dump_json())
        add_training_label(int(doc["id"]), "full_json", payload, labeled_by="ingest", db_path=db_path)
        if extraction.ocr_used:
            record_ocr_run(
                document_id=int(doc["id"]),
                source_path=doc["file_path"],
                engine="tesseract",
                page_count=extraction.page_count,
                db_path=db_path,
            )

    return doc


def sync_corrections_from_dir(
    corrections_dir: Path | str | None = None,
    *,
    db_path: str | Path = "data/app.db",
) -> dict[str, int]:
    """Импортирует JSONL из GUI в training_corrections."""
    root = Path(corrections_dir or TRAINING_CORRECTIONS_DIR)
    stats = {"files": 0, "rows": 0, "skipped": 0}
    if not root.is_dir():
        return stats

    with get_connection(db_path) as conn:
        for jsonl in sorted(root.glob("*.jsonl")):
            stats["files"] += 1
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    stats["skipped"] += 1
                    continue
                doc_name = row.get("doc") or ""
                doc_id: int | None = None
                if doc_name:
                    found = conn.execute(
                        "SELECT id FROM training_documents WHERE file_name = ? ORDER BY id DESC LIMIT 1",
                        (doc_name,),
                    ).fetchone()
                    if found:
                        doc_id = int(found[0])
                conn.execute(
                    """
                    INSERT INTO training_corrections (
                        document_id, field_name, original_value, corrected_value,
                        mark_context, exported_from, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        str(row.get("field") or "unknown"),
                        json.dumps(row.get("original"), ensure_ascii=False)
                        if row.get("original") is not None
                        else None,
                        json.dumps(row.get("corrected"), ensure_ascii=False)
                        if row.get("corrected") is not None
                        else str(row.get("corrected") or ""),
                        row.get("mark"),
                        "gui_confirm",
                        _now(),
                    ),
                )
                stats["rows"] += 1
    return stats


def register_rag_document(
    file_path: Path | str,
    *,
    title: str | None = None,
    doc_kind: RagDocKind,
    metadata: dict[str, Any] | None = None,
    db_path: str | Path = "data/app.db",
) -> dict[str, Any]:
    path = Path(file_path).resolve()
    rel = _rel_path(path)
    meta_path = path.with_suffix(path.suffix + ".meta.json")
    meta = dict(metadata or {})
    if meta_path.is_file():
        meta.update(json.loads(meta_path.read_text(encoding="utf-8")))

    text_length = 0
    if path.suffix.lower() in {".txt", ".md"}:
        text_length = len(path.read_text(encoding="utf-8", errors="replace"))
    else:
        # Фаза 1: только реестр; полный текст/embeddings — Фаза 4 (index-rag --deep)
        text_length = path.stat().st_size

    title = title or meta.get("title") or path.stem
    now = _now()

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM rag_documents WHERE file_path = ?",
            (rel,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE rag_documents SET
                    title = ?, doc_kind = ?, text_length = ?,
                    metadata_json = ?, indexed_at = ?
                WHERE id = ?
                """,
                (
                    title,
                    doc_kind,
                    text_length,
                    json.dumps(meta, ensure_ascii=False),
                    now,
                    existing[0],
                ),
            )
            rag_id = int(existing[0])
        else:
            cur = conn.execute(
                """
                INSERT INTO rag_documents (
                    title, doc_kind, file_path, text_length, chunk_count,
                    indexed_at, metadata_json
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (title, doc_kind, rel, text_length, now, json.dumps(meta, ensure_ascii=False)),
            )
            rag_id = int(cur.lastrowid)

    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM rag_documents WHERE id = ?", (rag_id,)).fetchone()
    return dict(row)


def index_rag_folder(
    folder: Path | str,
    *,
    doc_kind: RagDocKind | None = None,
    db_path: str | Path = "data/app.db",
) -> dict[str, int]:
    """Регистрирует файлы корпуса в rag_documents (без embeddings — Фаза 4)."""
    root = Path(folder).resolve()
    stats = {"indexed": 0, "skipped": 0}
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {s.lower() for s in RAG_SUFFIXES}:
            stats["skipped"] += 1
            continue
        if path.name.endswith(".meta.json"):
            stats["skipped"] += 1
            continue

        kind = doc_kind
        if kind is None:
            try:
                rel_parts = path.relative_to(RAG_CORPUS_DIR.resolve()).parts
                if rel_parts:
                    kind = RAG_FOLDER_KINDS.get(rel_parts[0], "internal")
            except ValueError:
                kind = "internal"

        register_rag_document(path, doc_kind=kind or "internal", db_path=db_path)
        stats["indexed"] += 1
    return stats


def import_extracted_fixtures(
    extracted_dir: Path | str | None = None,
    *,
    db_path: str | Path = "data/app.db",
) -> list[int]:
    """Импортирует data/extracted/*.json как training_documents + full_json labels."""
    root = Path(extracted_dir or EXTRACTED_DIR)
    ids: list[int] = []
    if not root.is_dir():
        return ids

    for json_path in sorted(root.glob("*.json")):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        source = data.get("source_path") or json_path.stem
        src_path = Path(source)
        if not src_path.is_file():
            continue
        doc = register_training_document(
            src_path,
            document_type=detect_document_type(data.get("text") or ""),
            label_status="complete",
            source="fixture",
            page_count=data.get("page_count"),
            db_path=db_path,
        )
        add_training_label(int(doc["id"]), "full_json", data, labeled_by="fixture", db_path=db_path)
        ids.append(int(doc["id"]))
    return ids


def seed_document_families(*, db_path: str | Path = "data/app.db") -> int:
    """Регистрирует YAML-семейства из data/families/ в document_families."""
    count = 0
    if not FAMILIES_DIR.is_dir():
        return count
    now = _now()
    with get_connection(db_path) as conn:
        for yaml_path in sorted(FAMILIES_DIR.glob("*.yaml")):
            import yaml

            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            family_id = cfg.get("id") or yaml_path.stem
            conn.execute(
                """
                INSERT INTO document_families (
                    id, display_name, document_type, config_path,
                    sender_patterns, enabled, priority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    document_type = excluded.document_type,
                    config_path = excluded.config_path,
                    sender_patterns = excluded.sender_patterns,
                    enabled = excluded.enabled,
                    priority = excluded.priority
                """,
                (
                    family_id,
                    cfg.get("display_name", family_id),
                    cfg.get("document_type", "unknown"),
                    _rel_path(yaml_path),
                    json.dumps(cfg.get("sender_patterns") or [], ensure_ascii=False),
                    1 if cfg.get("enabled", True) else 0,
                    int(cfg.get("priority", 100)),
                    now,
                ),
            )
            count += 1
    return count


def list_rag_documents(
    *,
    doc_kind: str | None = None,
    limit: int = 50,
    db_path: str | Path = "data/app.db",
) -> list[dict[str, Any]]:
    query = "SELECT id, title, doc_kind, file_path, text_length, indexed_at FROM rag_documents WHERE 1=1"
    params: list[Any] = []
    if doc_kind:
        query += " AND doc_kind = ?"
        params.append(doc_kind)
    query += " ORDER BY doc_kind, title LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def ingest_inbox_batch(
    *,
    move_to_registered: bool = True,
    db_path: str | Path = "data/app.db",
) -> dict[str, int]:
    stats = {"ok": 0, "fail": 0}
    if not TRAINING_INBOX.is_dir():
        return stats
    for path in sorted(TRAINING_INBOX.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".docx"}:
            continue
        try:
            ingest_training_document(
                path,
                move_to_registered=move_to_registered,
                db_path=db_path,
            )
            stats["ok"] += 1
        except Exception:
            stats["fail"] += 1
    return stats