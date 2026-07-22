"""
Импорт каркаса требований из локального текста ТУ (raw .txt).

Не коммитит файлы: только пишет в SQLite. Эвристика пунктов «N.N …».
Полный юридический разбор ТУ — не цель v1.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..persistence.sqlite_repo import (
    DB_PATH_DEFAULT,
    add_test_alias,
    get_connection,
)

# Строка вида: 1.4.1 Текст требования...
_CLAUSE_LINE = re.compile(
    r"^\s*(\d+(?:\.\d+){1,4})\s+(.{8,200}?)\s*$",
)
# Таблица ПМИ/ТУ: «С1 | Проверка конструкции | 2.3.1 - 2.3.6 | 5.2»
_PIPE_TABLE_ROW = re.compile(
    r"^\s*\S+\s*\|\s*(?P<title>[^|]{6,160}?)\s*\|\s*(?P<clause>[\d.,\s\-–—]+)\s*\|",
)
_INTERESTING = re.compile(
    r"испытан|сопротивлен|провер|измерен|нагружен|изгиб|температур|"
    r"влажност|горен|огнест|экран|емкост|напряжен|герметич|обрыв|"
    r"затухан|кручен|удар|раздавл|растяг|маркиров",
    re.IGNORECASE,
)


def _doc_id_from_path(path: Path) -> str:
    stem = path.stem.strip()
    # normalize en/em dash
    stem = stem.replace("–", "-").replace("—", "-")
    if not stem.upper().startswith("ТУ") and re.match(r"^\d", stem):
        return f"ТУ-{stem}"
    return stem[:120]


def extract_clauses_from_text(
    text: str,
    *,
    max_clauses: int = 80,
) -> list[tuple[str, str]]:
    """Возвращает [(clause, title), …] отфильтрованные «интересные» пункты."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.replace("\xa0", " ").strip()
        if len(line) < 12:
            continue
        clause: str | None = None
        title: str | None = None
        m = _CLAUSE_LINE.match(line)
        if m:
            clause, title = m.group(1), m.group(2).strip(" .;—-")
        else:
            pm = _PIPE_TABLE_ROW.match(line)
            if pm:
                title = pm.group("title").strip(" .;—-")
                raw_cl = (pm.group("clause") or "").strip()
                # берём первый пункт «2.3.1» из диапазона
                cm = re.search(r"\d+(?:\.\d+){1,4}", raw_cl)
                clause = cm.group(0) if cm else raw_cl[:32]
        if not clause or not title:
            continue
        key = f"{clause}|{title[:40].lower()}"
        if key in seen or clause in seen and len(title) < 20:
            continue
        if not _INTERESTING.search(title) and not _INTERESTING.search(line):
            # keep some structural if short clause list still empty later
            if len(found) > 15:
                continue
        seen.add(key)
        seen.add(clause)
        found.append((clause, title[:240]))
        if len(found) >= max_clauses:
            break
    return found


def import_norm_from_text_file(
    path: Path | str,
    *,
    kind: str = "tu",
    db_path: Path | str = DB_PATH_DEFAULT,
    max_clauses: int = 80,
) -> dict[str, Any]:
    """Регистрирует norm_document + requirements из .txt (локальный корпус)."""
    from datetime import datetime

    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(str(file_path))
    text = file_path.read_text(encoding="utf-8", errors="replace")
    doc_id = _doc_id_from_path(file_path)
    title = f"{doc_id} (импорт raw_text)"
    clauses = extract_clauses_from_text(text, max_clauses=max_clauses)
    now = datetime.now().isoformat()

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO norm_documents (doc_id, title, kind, file_path, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                title = excluded.title,
                file_path = excluded.file_path,
                notes = excluded.notes
            """,
            (
                doc_id,
                title,
                kind,
                str(file_path.resolve()),
                f"import_norm_from_text; clauses={len(clauses)}",
                now,
            ),
        )
        row = conn.execute(
            "SELECT id FROM norm_documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        nd_id = int(row["id"])
        inserted = 0
        for clause, ctitle in clauses:
            cur = conn.execute(
                """
                INSERT INTO requirements
                    (norm_document_id, clause, title, body, created_at)
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(norm_document_id, clause) DO UPDATE SET
                    title = excluded.title
                """,
                (nd_id, clause, ctitle, now),
            )
            if cur.rowcount:
                inserted += 1

    return {
        "doc_id": doc_id,
        "norm_document_id": nd_id,
        "clauses": len(clauses),
        "path": str(file_path),
        "kind": kind,
    }


def import_aliases_from_synonyms_yaml(
    path: Path | str,
    *,
    db_path: Path | str = DB_PATH_DEFAULT,
) -> int:
    """Импорт data/knowledge/…/test_synonyms.yaml → test_aliases (+ note)."""
    import yaml

    file_path = Path(path)
    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    synonyms = data.get("synonyms") or []
    n = 0
    for item in synonyms:
        if not isinstance(item, dict):
            continue
        phrase = (item.get("phrase") or "").strip()
        code = (item.get("canonical_code") or item.get("code") or "").strip()
        if not phrase:
            continue
        add_test_alias(
            phrase,
            phrase,  # canonical display = phrase until mapped better
            price_test_code=code or None,
            source="test_synonyms.yaml",
            db_path=db_path,
        )
        n += 1
    return n
