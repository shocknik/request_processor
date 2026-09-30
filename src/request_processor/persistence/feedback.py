"""Журнал пожеланий оператора (feedback_journal)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .db import DB_PATH_DEFAULT, get_connection

FEEDBACK_STATUS_LABELS: dict[str, str] = {
    "new": "новое",
    "in_progress": "в работе",
    "done": "сделано",
    "wontfix": "не будем",
}
_FEEDBACK_STATUS_ALIASES: dict[str, str] = {
    "new": "new",
    "новое": "new",
    "in_progress": "in_progress",
    "в работе": "in_progress",
    "вработе": "in_progress",
    "done": "done",
    "сделано": "done",
    "готово": "done",
    "wontfix": "wontfix",
    "не будем": "wontfix",
    "небудем": "wontfix",
    "отклонено": "wontfix",
}


def normalize_feedback_status(value: str | None) -> str:
    """Ключ статуса журнала: new / in_progress / done / wontfix."""
    raw = (value or "new").strip().lower()
    key = _FEEDBACK_STATUS_ALIASES.get(raw, "new")
    return key if key in FEEDBACK_STATUS_LABELS else "new"


def feedback_status_label(value: str | None) -> str:
    return FEEDBACK_STATUS_LABELS[normalize_feedback_status(value)]


def _migrate_feedback_journal(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """Журнал пожеланий / ошибок / обратной связи оператора (меню Файл)."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS feedback_journal (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TEXT NOT NULL,
                category        TEXT NOT NULL,
                section         TEXT,
                priority        TEXT NOT NULL DEFAULT 'обычный',
                title           TEXT NOT NULL,
                body            TEXT NOT NULL,
                steps           TEXT,
                expected        TEXT,
                actual          TEXT,
                app_version     TEXT,
                host_name       TEXT,
                status          TEXT NOT NULL DEFAULT 'new',
                source          TEXT NOT NULL DEFAULT 'gui'
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_journal_created
                ON feedback_journal(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_journal_category
                ON feedback_journal(category);
            """
        )


def add_feedback_entry(
    *,
    category: str,
    title: str,
    body: str,
    section: str | None = None,
    priority: str = "обычный",
    steps: str | None = None,
    expected: str | None = None,
    actual: str | None = None,
    app_version: str | None = None,
    host_name: str | None = None,
    status: str = "new",
    source: str = "gui",
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Добавить запись в журнал обратной связи. Возвращает id."""
    import socket

    title_s = (title or "").strip()
    body_s = (body or "").strip()
    if not title_s:
        raise ValueError("Укажите краткий заголовок")
    if len(body_s) < 3:
        raise ValueError("Опишите пожелание или проблему (свободный текст)")
    cat = (category or "пожелание").strip() or "пожелание"
    prio = (priority or "обычный").strip() or "обычный"
    now = datetime.now().isoformat(timespec="seconds")
    host = (host_name or "").strip() or (socket.gethostname() or "")
    ver = app_version
    if not ver:
        try:
            import request_processor as rp

            ver = getattr(rp, "__version__", None)
        except Exception:
            ver = None
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO feedback_journal (
                created_at, category, section, priority, title, body,
                steps, expected, actual, app_version, host_name, status, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                cat,
                (section or "").strip() or None,
                prio,
                title_s,
                body_s,
                (steps or "").strip() or None,
                (expected or "").strip() or None,
                (actual or "").strip() or None,
                ver,
                host or None,
                normalize_feedback_status(status),
                source or "gui",
            ),
        )
        return int(cur.lastrowid or 0)


def list_feedback_entries(
    *,
    limit: int = 200,
    status: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    """Список записей журнала (новые сверху)."""
    with get_connection(db_path) as conn:
        if status and status != "all":
            key = normalize_feedback_status(status)
            rows = conn.execute(
                """
                SELECT * FROM feedback_journal
                WHERE status = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (key, max(1, int(limit))),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM feedback_journal
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(r) for r in rows]


def update_feedback_status(
    entry_id: int,
    status: str,
    *,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> bool:
    """Сменить статус записи (новое / в работе / сделано / не будем)."""
    key = normalize_feedback_status(status)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE feedback_journal SET status = ? WHERE id = ?",
            (key, int(entry_id)),
        )
        return cur.rowcount > 0


def get_feedback_entry(
    entry_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM feedback_journal WHERE id = ?",
            (entry_id,),
        ).fetchone()
        return dict(row) if row else None


def export_feedback_journal(
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    since_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Все (или с даты) записи для prod-data zip."""
    with get_connection(db_path) as conn:
        if since_iso:
            rows = conn.execute(
                """
                SELECT * FROM feedback_journal
                WHERE created_at >= ?
                ORDER BY id ASC
                """,
                (since_iso,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM feedback_journal ORDER BY id ASC"
            ).fetchall()
        return [dict(r) for r in rows]


def import_feedback_entries(
    entries: list[dict[str, Any]],
    *,
    db_path: str | Path = DB_PATH_DEFAULT,
    station_prefix: str = "",
) -> int:
    """Импорт записей с work (не дублируем по title+created_at+body hash)."""
    if not entries:
        return 0
    n = 0
    with get_connection(db_path) as conn:
        for e in entries:
            title = (e.get("title") or "").strip()
            body = (e.get("body") or "").strip()
            created = (e.get("created_at") or "").strip()
            if not title or not body:
                continue
            exists = conn.execute(
                """
                SELECT id, status FROM feedback_journal
                WHERE title = ? AND body = ? AND created_at = ?
                LIMIT 1
                """,
                (title, body, created),
            ).fetchone()
            if exists:
                incoming = normalize_feedback_status(e.get("status"))
                if incoming != normalize_feedback_status(exists["status"]):
                    conn.execute(
                        "UPDATE feedback_journal SET status = ? WHERE id = ?",
                        (incoming, int(exists["id"])),
                    )
                    n += 1
                continue
            # пометка источника станции в host_name
            host = (e.get("host_name") or "").strip()
            if station_prefix and station_prefix not in host:
                host = f"{station_prefix}:{host}" if host else station_prefix
            conn.execute(
                """
                INSERT INTO feedback_journal (
                    created_at, category, section, priority, title, body,
                    steps, expected, actual, app_version, host_name, status, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created or datetime.now().isoformat(timespec="seconds"),
                    e.get("category") or "пожелание",
                    e.get("section"),
                    e.get("priority") or "обычный",
                    title,
                    body,
                    e.get("steps"),
                    e.get("expected"),
                    e.get("actual"),
                    e.get("app_version"),
                    host or None,
                    normalize_feedback_status(e.get("status")),
                    e.get("source") or "import",
                ),
            )
            n += 1
    return n
