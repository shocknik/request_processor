"""
Журнал решений оператора по подсказкам ассистента (принять / отклонить).

Пишет:
  - data/training/corrections/assistant_*.jsonl  (для обучения / sync-corrections)
  - assistant_sessions в SQLite (короткий audit trail)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..config import DB_PATH_DEFAULT, TRAINING_CORRECTIONS_DIR
from ..persistence.sqlite_repo import get_connection

FeedbackDecision = Literal["accepted", "rejected", "applied_batch", "shown"]


@dataclass
class AssistantFeedbackEvent:
    """Одно решение оператора по подсказке."""

    decision: FeedbackDecision
    raw: str
    suggested: str
    confidence: float
    source: str
    reason: str = ""
    document: str = ""
    mark_index: int | None = None
    session_id: str = ""

    def to_jsonl_row(self) -> dict:
        return {
            "field": "mark",
            "change": "assistant_" + self.decision,
            "original": self.raw,
            "corrected": self.suggested if self.decision in ("accepted", "applied_batch") else self.raw,
            "assistant_suggested": self.suggested,
            "decision": self.decision,
            "confidence": self.confidence,
            "source": self.source,
            "reason": self.reason,
            "mark": self.suggested if self.decision in ("accepted", "applied_batch") else self.raw,
            "doc": self.document,
            "session_id": self.session_id,
            "at": datetime.now().isoformat(timespec="seconds"),
        }


def append_assistant_feedback(
    events: list[AssistantFeedbackEvent],
    *,
    corrections_dir: Path | str | None = None,
    db_path: Path | str = DB_PATH_DEFAULT,
    write_db: bool = True,
) -> Path | None:
    """
    Дописывает события в JSONL и (опционально) в assistant_sessions.

    Returns:
        путь к jsonl или None, если events пуст.
    """
    if not events:
        return None

    out_dir = Path(corrections_dir or TRAINING_CORRECTIONS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = events[0].session_id or stamp
    out_file = out_dir / f"assistant_{stamp}_{session[:8]}.jsonl"
    lines = [json.dumps(e.to_jsonl_row(), ensure_ascii=False) for e in events]
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if write_db:
        try:
            _write_assistant_sessions(events, db_path=db_path)
        except Exception:  # noqa: BLE001 — журнал не должен ронять GUI
            pass

    return out_file


def _write_assistant_sessions(
    events: list[AssistantFeedbackEvent],
    *,
    db_path: Path | str,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection(db_path) as conn:
        for e in events:
            message = json.dumps(
                {
                    "raw": e.raw,
                    "suggested": e.suggested,
                    "confidence": e.confidence,
                    "source": e.source,
                    "reason": e.reason,
                    "doc": e.document,
                },
                ensure_ascii=False,
            )
            conn.execute(
                """
                INSERT INTO assistant_sessions (
                    order_id, document_id, role, message, response, model, feedback, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    None,
                    None,
                    "mark_corrector",
                    message,
                    e.suggested,
                    e.source,
                    e.decision,
                    now,
                ),
            )


def list_recent_assistant_feedback(
    *,
    limit: int = 50,
    db_path: Path | str = DB_PATH_DEFAULT,
) -> list[dict]:
    """Последние записи из assistant_sessions (для отладки / вкладки истории)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, role, message, response, model, feedback, created_at
            FROM assistant_sessions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
