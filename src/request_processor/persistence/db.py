"""Подключение к SQLite и пути к файлу базы."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..config import DB_PATH_DEFAULT, PROJECT_ROOT
from ..logging_setup import get_logger

_log = get_logger("persistence")

def resolve_db_path(db_path: str | Path = DB_PATH_DEFAULT) -> Path:
    """Абсолютный путь к БД; относительные пути — от cwd, кроме стандартного data/app.db."""
    p = Path(db_path)
    if p.is_absolute():
        return p
    if p.as_posix() == "data/app.db":
        return (PROJECT_ROOT / p).resolve()
    return (Path.cwd() / p).resolve()


@contextmanager
def get_connection(db_path: str | Path = DB_PATH_DEFAULT):
    """
    Контекстный менеджер подключения к SQLite.
    
    Преимущества:
    - Автоматически commit при успехе и close при любом исходе
    - Включает foreign_keys (для целостности данных)
    - row_factory = sqlite3.Row → можно обращаться как к dict
    """
    db_path = resolve_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
