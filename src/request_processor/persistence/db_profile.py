"""
Роль активной SQLite-базы: dev / work_copy / work.

Файл ``data/app.db`` всегда «то, что открывает приложение».
Различие — в метке ``data/db_profile.local.yaml`` (не в git):

- **dev** — локальная тестовая на ПК разработки; **не** источник истины.
- **work_copy** — копия с рабочего ПК на dev; для данных орг/заказов/прайса —
  источник истины, пока оператор так разметил.
- **work** — боевая БД на рабочем ПК.

Агент и оператор не должны чинить «грязные» org в dev-БД как prod-данные.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ..config import DATA_DIR, DB_PATH_DEFAULT

DbRole = Literal["dev", "work_copy", "work"]

VALID_ROLES: frozenset[str] = frozenset({"dev", "work_copy", "work"})

# Имя по умолчанию (когда БД = data/app.db). Для других файлов — см. profile_path_for_db.
PROFILE_FILENAME = "db_profile.local.yaml"
PROFILE_PATH_DEFAULT = DATA_DIR / PROFILE_FILENAME

_ROLE_UI: dict[str, str] = {
    "dev": "тестовая",
    "work_copy": "копия рабочей",
    "work": "рабочая",
}

_ROLE_SHORT: dict[str, str] = {
    "dev": "DEV",
    "work_copy": "WORK-COPY",
    "work": "WORK",
}


@dataclass
class DbProfile:
    """Локальная метка роли активной БД."""

    role: DbRole = "dev"
    label: str = ""
    source: str = ""
    notes: str = ""
    marked_at: str = ""
    # Подсказка «файл сменили, а метку забыли»
    db_file: str = "app.db"
    size_bytes: int | None = None
    mtime_iso: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def is_source_of_truth(self) -> bool:
        """Данные оператора (орг, заказы, прайс) считать авторитетными."""
        return self.role in ("work", "work_copy")

    @property
    def is_dev_scratch(self) -> bool:
        return self.role == "dev"

    def ui_label(self) -> str:
        if self.label.strip():
            return self.label.strip()
        return _ROLE_UI.get(self.role, self.role)

    def window_title_suffix(self) -> str:
        tag = _ROLE_SHORT.get(self.role, self.role.upper())
        return f"БД: {self.ui_label()} [{tag}]"

    def status_line(self) -> str:
        parts = [f"БД: {self.ui_label()}"]
        if self.source.strip():
            parts.append(f"источник: {self.source.strip()}")
        if self.is_dev_scratch:
            parts.append("не источник истины")
        elif self.role == "work_copy":
            parts.append("копия с рабочего ПК")
        return " · ".join(parts)


def profile_path_for_db(db_path: Path | str | None = None) -> Path:
    """Путь к yaml-метке **для конкретного файла** БД.

    - ``data/app.db`` → ``data/db_profile.local.yaml`` (короткое имя для основного файла)
    - ``data/test_smoke.db`` → ``data/test_smoke.db.profile.yaml``
    - любой другой путь → ``<stem>.db.profile.yaml`` рядом с файлом

    Раньше все ``*.db`` в ``data/`` делили одну метку — роли перетирались.
    """
    if db_path is None:
        return PROFILE_PATH_DEFAULT
    p = Path(db_path).resolve()
    # Основная БД приложения — привычное имя метки
    if p.name.lower() == "app.db":
        return p.parent / PROFILE_FILENAME
    # Остальные: per-file sidecar
    return p.parent / f"{p.name}.profile.yaml"


def _file_fingerprint(db_path: Path) -> tuple[int | None, str | None]:
    if not db_path.is_file():
        return None, None
    try:
        st = db_path.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        return int(st.st_size), mtime
    except OSError:
        return None, None


def load_db_profile(
    db_path: Path | str | None = None,
    *,
    profile_path: Path | str | None = None,
) -> DbProfile:
    """Читает метку; при отсутствии файла — dev (тестовая) с пустым source."""
    db = Path(db_path) if db_path is not None else Path(DB_PATH_DEFAULT)
    path = Path(profile_path) if profile_path is not None else profile_path_for_db(db)

    if not path.is_file():
        size, mtime = _file_fingerprint(db)
        return DbProfile(
            role="dev",
            label="тестовая (не размечена)",
            source="",
            notes=(
                "Файл db_profile.local.yaml отсутствует. "
                "Считаем БД тестовой. После копирования с рабочего ПК: "
                "request-processor db-role --set work_copy --source \"…\""
            ),
            marked_at="",
            db_file=db.name,
            size_bytes=size,
            mtime_iso=mtime,
        )

    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        size, mtime = _file_fingerprint(db)
        return DbProfile(
            role="dev",
            label="тестовая (ошибка чтения метки)",
            notes=f"Не удалось прочитать {path.name}",
            db_file=db.name,
            size_bytes=size,
            mtime_iso=mtime,
        )

    if not isinstance(raw, dict):
        raw = {}

    role_raw = str(raw.get("role") or "dev").strip().lower()
    role: DbRole = role_raw if role_raw in VALID_ROLES else "dev"  # type: ignore[assignment]

    size, mtime = _file_fingerprint(db)
    return DbProfile(
        role=role,
        label=str(raw.get("label") or "").strip(),
        source=str(raw.get("source") or "").strip(),
        notes=str(raw.get("notes") or "").strip(),
        marked_at=str(raw.get("marked_at") or "").strip(),
        db_file=str(raw.get("db_file") or db.name).strip() or db.name,
        size_bytes=size if size is not None else raw.get("size_bytes"),
        mtime_iso=mtime if mtime is not None else (str(raw.get("mtime_iso") or "") or None),
        extra={k: v for k, v in raw.items() if k not in {
            "role", "label", "source", "notes", "marked_at", "db_file",
            "size_bytes", "mtime_iso",
        }},
    )


def save_db_profile(
    profile: DbProfile,
    db_path: Path | str | None = None,
    *,
    profile_path: Path | str | None = None,
) -> Path:
    """Пишет ``db_profile.local.yaml`` рядом с БД."""
    import yaml

    db = Path(db_path) if db_path is not None else Path(DB_PATH_DEFAULT)
    path = Path(profile_path) if profile_path is not None else profile_path_for_db(db)
    path.parent.mkdir(parents=True, exist_ok=True)

    size, mtime = _file_fingerprint(db)
    payload = {
        "role": profile.role,
        "label": profile.label or _ROLE_UI.get(profile.role, profile.role),
        "source": profile.source,
        "notes": profile.notes,
        "marked_at": profile.marked_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_file": db.name,
        "size_bytes": size,
        "mtime_iso": mtime,
    }
    for k, v in (profile.extra or {}).items():
        if k not in payload:
            payload[k] = v

    path.write_text(
        "# Локальная метка роли БД (не коммитить).\n"
        "# См. docs/db_profile.example.yaml\n"
        + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def set_db_role(
    role: DbRole,
    *,
    db_path: Path | str | None = None,
    source: str = "",
    notes: str = "",
    label: str = "",
) -> DbProfile:
    """Устанавливает роль активной БД и сохраняет метку."""
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}")
    db = Path(db_path) if db_path is not None else Path(DB_PATH_DEFAULT)
    profile = DbProfile(
        role=role,
        label=label or _ROLE_UI[role],
        source=source,
        notes=notes,
        marked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        db_file=db.name,
    )
    save_db_profile(profile, db)
    return load_db_profile(db)


def format_db_info(
    db_path: Path | str | None = None,
    *,
    profile: DbProfile | None = None,
) -> str:
    """Многострочный отчёт для CLI / логов."""
    db = Path(db_path) if db_path is not None else Path(DB_PATH_DEFAULT)
    prof = profile if profile is not None else load_db_profile(db)
    lines = [
        f"db_path:     {db.resolve()}",
        f"exists:      {db.is_file()}",
        f"role:        {prof.role}",
        f"label:       {prof.ui_label()}",
        f"truth:       {'yes (work/work_copy)' if prof.is_source_of_truth else 'no (dev scratch)'}",
        f"source:      {prof.source or '—'}",
        f"marked_at:   {prof.marked_at or '—'}",
        f"profile:     {profile_path_for_db(db)}",
        f"size_bytes:  {prof.size_bytes if prof.size_bytes is not None else '—'}",
        f"mtime:       {prof.mtime_iso or '—'}",
    ]
    if prof.notes:
        lines.append(f"notes:       {prof.notes}")
    if prof.is_dev_scratch:
        lines.append(
            "hint:        не правьте org/заказы здесь как prod; "
            "после копии с рабочего ПК: db-role --set work_copy"
        )
    return "\n".join(lines)


def profile_to_dict(profile: DbProfile) -> dict:
    return asdict(profile)
