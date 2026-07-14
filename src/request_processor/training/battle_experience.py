"""
Пакет боевого опыта — перенос данных с рабочего ПК на машину разработки.

Собирает:
  - правки оператора (data/training/corrections/*.jsonl)
  - снимки парсинга (data/parse_snapshots/)
  - журнал ассистента (assistant_sessions)
  - использованные test_mappings (для улучшения маппера)

Формат: zip с manifest.json (версия 1).
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import socket
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import (
    DB_PATH_DEFAULT,
    PARSE_SNAPSHOTS_DIR,
    TRAINING_CORRECTIONS_DIR,
)
from ..persistence.sqlite_repo import get_connection
from ..persistence.training_repo import sync_corrections_from_dir

FORMAT_VERSION = 1
BATTLE_HOST_ID_KEY = "battle_host_id"
LAST_BATTLE_EXPORT_KEY = "last_battle_export_at"
BATTLE_IMPORT_LOG_KEY = "battle_import_log"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_host_slug() -> str:
    name = (socket.gethostname() or "host").strip()
    slug = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE).strip("_")
    return (slug[:32] or "host").lower()


def _get_app_setting(key: str, db_path: Path | str) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def _set_app_setting(key: str, value: str, db_path: Path | str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def get_battle_host_id(db_path: Path | str = DB_PATH_DEFAULT) -> str:
    """Стабильный ID рабочей станции (для префикса файлов при импорте)."""
    existing = _get_app_setting(BATTLE_HOST_ID_KEY, db_path)
    if existing:
        return existing
    host = _safe_host_slug()
    uid = uuid.uuid4().hex[:8]
    host_id = f"{host}_{uid}"
    _set_app_setting(BATTLE_HOST_ID_KEY, host_id, db_path)
    return host_id


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _collect_correction_files(
    *,
    since_ts: float | None,
    corrections_dir: Path,
) -> list[Path]:
    if not corrections_dir.is_dir():
        return []
    files = sorted(corrections_dir.glob("*.jsonl"))
    if since_ts is None:
        return files
    return [f for f in files if _file_mtime(f) > since_ts]


def _collect_snapshots(
    *,
    since_ts: float | None,
    snapshots_dir: Path,
    limit: int,
) -> list[Path]:
    if not snapshots_dir.is_dir():
        return []
    files = sorted(
        snapshots_dir.glob("*.json"),
        key=_file_mtime,
        reverse=True,
    )
    if since_ts is not None:
        files = [f for f in files if _file_mtime(f) > since_ts]
    return files[:limit]


def _export_assistant_sessions(db_path: Path | str) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, role, message, response, model, feedback, created_at
            FROM assistant_sessions
            ORDER BY id DESC
            LIMIT 500
            """
        ).fetchall()
    return [dict(r) for r in rows]


def _export_test_mappings(db_path: Path | str, *, min_usage: int = 1) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, requirement_pattern, test_code, note, usage_count, created_at
            FROM test_mappings
            WHERE usage_count >= ?
            ORDER BY usage_count DESC, id DESC
            """,
            (min_usage,),
        ).fetchall()
    return [dict(r) for r in rows]


def _battle_stats(db_path: Path | str) -> dict[str, int]:
    with get_connection(db_path) as conn:
        orders = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
        extractions = conn.execute("SELECT COUNT(*) AS c FROM document_extractions").fetchone()["c"]
        corrections = conn.execute("SELECT COUNT(*) AS c FROM training_corrections").fetchone()["c"]
        sessions = conn.execute("SELECT COUNT(*) AS c FROM assistant_sessions").fetchone()["c"]
    return {
        "orders": int(orders),
        "document_extractions": int(extractions),
        "training_corrections": int(corrections),
        "assistant_sessions": int(sessions),
    }


def export_battle_experience(
    output_path: Path | str,
    *,
    db_path: Path | str = DB_PATH_DEFAULT,
    corrections_dir: Path | str = TRAINING_CORRECTIONS_DIR,
    snapshots_dir: Path | str = PARSE_SNAPSHOTS_DIR,
    delta_only: bool = True,
    snapshot_limit: int = 50,
    operator_note: str = "",
) -> dict[str, Any]:
    """
    Создаёт zip-пакет боевого опыта.

    Args:
        delta_only: только файлы corrections/snapshots новее последнего экспорта
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    corr_dir = Path(corrections_dir)
    snap_dir = Path(snapshots_dir)

    host_id = get_battle_host_id(db_path)
    last_export = _get_app_setting(LAST_BATTLE_EXPORT_KEY, db_path)
    since_ts: float | None = None
    if delta_only and last_export:
        try:
            since_ts = datetime.fromisoformat(last_export).timestamp()
        except ValueError:
            since_ts = None

    correction_files = _collect_correction_files(since_ts=since_ts, corrections_dir=corr_dir)
    snapshot_files = _collect_snapshots(
        since_ts=since_ts,
        snapshots_dir=snap_dir,
        limit=snapshot_limit,
    )
    sessions = _export_assistant_sessions(db_path)
    mappings = _export_test_mappings(db_path)
    stats = _battle_stats(db_path)

    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": _now_iso(),
        "host_id": host_id,
        "host_name": socket.gethostname(),
        "platform": platform.platform(),
        "delta_only": delta_only,
        "since_export": last_export if delta_only else None,
        "operator_note": operator_note.strip(),
        "counts": {
            "correction_files": len(correction_files),
            "snapshots": len(snapshot_files),
            "assistant_sessions": len(sessions),
            "test_mappings_used": len(mappings),
        },
        "db_stats": stats,
    }

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path in correction_files:
            arc = f"corrections/{path.name}"
            zf.write(path, arcname=arc)
        for path in snapshot_files:
            arc = f"parse_snapshots/{path.name}"
            zf.write(path, arcname=arc)
        if sessions:
            lines = [json.dumps(s, ensure_ascii=False) for s in sessions]
            zf.writestr("assistant_sessions.jsonl", "\n".join(lines) + "\n")
        if mappings:
            zf.writestr(
                "test_mappings_used.json",
                json.dumps(mappings, ensure_ascii=False, indent=2),
            )

    _set_app_setting(LAST_BATTLE_EXPORT_KEY, manifest["exported_at"], db_path)
    return {
        "path": str(out.resolve()),
        "manifest": manifest,
    }


def _append_import_log(entry: dict[str, Any], db_path: Path | str) -> None:
    raw = _get_app_setting(BATTLE_IMPORT_LOG_KEY, db_path)
    log: list[dict[str, Any]] = []
    if raw:
        try:
            log = json.loads(raw)
        except json.JSONDecodeError:
            log = []
    log.insert(0, entry)
    _set_app_setting(BATTLE_IMPORT_LOG_KEY, json.dumps(log[:20], ensure_ascii=False), db_path)


def _unique_dest(dest_dir: Path, name: str, host_prefix: str) -> Path:
    candidate = dest_dir / f"{host_prefix}_{name}"
    if not candidate.exists():
        return candidate
    stem = Path(name).stem
    suffix = Path(name).suffix
    n = 2
    while True:
        alt = dest_dir / f"{host_prefix}_{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


def _content_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def import_battle_experience(
    archive_path: Path | str,
    *,
    db_path: Path | str = DB_PATH_DEFAULT,
    corrections_dir: Path | str = TRAINING_CORRECTIONS_DIR,
    snapshots_dir: Path | str = PARSE_SNAPSHOTS_DIR,
    sync_db: bool = True,
) -> dict[str, Any]:
    """
    Импортирует zip с рабочего ПК в дерево data/ разработчика.

    Файлы получают префикс host_id из manifest, чтобы не затирать локальные.
    """
    archive = Path(archive_path)
    if not archive.is_file():
        raise FileNotFoundError(f"Архив не найден: {archive}")

    corr_dest = Path(corrections_dir)
    snap_dest = Path(snapshots_dir)
    corr_dest.mkdir(parents=True, exist_ok=True)
    snap_dest.mkdir(parents=True, exist_ok=True)

    stats = {
        "corrections_copied": 0,
        "corrections_skipped_duplicate": 0,
        "snapshots_copied": 0,
        "snapshots_skipped": 0,
        "sessions_appended": 0,
        "test_mappings_file": False,
    }
    manifest: dict[str, Any] = {}
    host_prefix = "unknown"

    with zipfile.ZipFile(archive, "r") as zf:
        if "manifest.json" in zf.namelist():
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            host_prefix = str(manifest.get("host_id") or manifest.get("host_name") or "battle")
            host_prefix = re.sub(r"[^\w.\-]+", "_", host_prefix).strip("_")[:40] or "battle"

        existing_hashes = {
            _content_hash(p) for p in corr_dest.glob("*.jsonl") if p.is_file()
        }

        for name in zf.namelist():
            if name.startswith("corrections/") and name.endswith(".jsonl"):
                data = zf.read(name)
                digest = hashlib.sha256(data).hexdigest()[:16]
                if digest in existing_hashes:
                    stats["corrections_skipped_duplicate"] += 1
                    continue
                dest = _unique_dest(corr_dest, Path(name).name, host_prefix)
                dest.write_bytes(data)
                existing_hashes.add(digest)
                stats["corrections_copied"] += 1

            elif name.startswith("parse_snapshots/") and name.endswith(".json"):
                dest = _unique_dest(snap_dest, Path(name).name, host_prefix)
                if dest.exists():
                    stats["snapshots_skipped"] += 1
                    continue
                dest.write_bytes(zf.read(name))
                stats["snapshots_copied"] += 1

        if "assistant_sessions.jsonl" in zf.namelist():
            sess_dest = _unique_dest(
                corr_dest,
                "imported_assistant_sessions.jsonl",
                host_prefix,
            )
            sess_dest.write_bytes(zf.read("assistant_sessions.jsonl"))
            stats["sessions_appended"] = 1

        if "test_mappings_used.json" in zf.namelist():
            ref_dir = corr_dest.parent / "imports"
            ref_dir.mkdir(parents=True, exist_ok=True)
            ref_path = _unique_dest(ref_dir, "test_mappings_used.json", host_prefix)
            ref_path.write_bytes(zf.read("test_mappings_used.json"))
            stats["test_mappings_file"] = True

    sync_stats: dict[str, int] = {}
    if sync_db and stats["corrections_copied"] > 0:
        sync_stats = sync_corrections_from_dir(corr_dest, db_path=db_path)

    result = {
        "archive": str(archive.resolve()),
        "manifest": manifest,
        "host_prefix": host_prefix,
        "stats": stats,
        "sync_corrections": sync_stats,
        "imported_at": _now_iso(),
    }
    _append_import_log(
        {
            "imported_at": result["imported_at"],
            "host_id": manifest.get("host_id"),
            "host_name": manifest.get("host_name"),
            "archive": archive.name,
            "stats": stats,
        },
        db_path,
    )
    return result