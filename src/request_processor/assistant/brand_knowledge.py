"""База знаний по маркам: SQLite cable_marks + KB manufacturer_v1."""

from __future__ import annotations

from pathlib import Path

from ..config import DB_PATH_DEFAULT, PROJECT_ROOT
from ..extraction.ocr_mark_normalizer import load_known_brands_from_db

_KB_BRANDS = PROJECT_ROOT / "data" / "knowledge" / "manufacturer_v1" / "brands.yaml"
_KB_MARKS = PROJECT_ROOT / "data" / "knowledge" / "manufacturer_v1" / "mark_templates.yaml"


def _load_kb_brands() -> set[str]:
    if not _KB_BRANDS.is_file():
        return set()
    try:
        import yaml

        data = yaml.safe_load(_KB_BRANDS.read_text(encoding="utf-8")) or {}
        out: set[str] = set()
        for row in data.get("brands") or []:
            b = str(row.get("brand") or "").strip()
            if b and len(b) >= 2:
                out.add(b)
        return out
    except Exception:
        return set()


def _load_kb_full_marks(*, limit: int = 800) -> set[str]:
    if not _KB_MARKS.is_file():
        return set()
    try:
        import yaml

        data = yaml.safe_load(_KB_MARKS.read_text(encoding="utf-8")) or {}
        out: set[str] = set()
        for row in data.get("templates") or []:
            m = str(row.get("example_full") or "").strip()
            if m and len(m) >= 5:
                out.add(m)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return set()


class BrandKnowledgeBase:
    """Кэш брендов и полных обозначений: БД + knowledge base ТУ."""

    def __init__(self, db_path: Path | str = DB_PATH_DEFAULT) -> None:
        self._db_path = Path(db_path)
        self._brands: set[str] | None = None
        self._full_marks: set[str] | None = None

    def brands(self) -> set[str]:
        if self._brands is None:
            self._brands = load_known_brands_from_db(self._db_path) | _load_kb_brands()
        return set(self._brands)

    def full_marks(self, *, limit: int = 500) -> set[str]:
        if self._full_marks is None:
            from ..persistence.sqlite_repo import list_cable_marks

            marks: set[str] = set()
            for row in list_cable_marks(limit=limit, db_path=self._db_path):
                mark = (
                    row.get("full_mark")
                    or row.get("mark")
                    or row.get("designation")
                    or ""
                )
                mark = str(mark).strip()
                if mark and len(mark) >= 3:
                    marks.add(mark)
            marks |= _load_kb_full_marks(limit=max(limit, 800))
            self._full_marks = marks
        return set(self._full_marks)

    def reload(self) -> None:
        self._brands = None
        self._full_marks = None
