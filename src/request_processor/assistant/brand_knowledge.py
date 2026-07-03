"""База знаний по маркам кабелей из SQLite (насмотренность ассистента)."""

from __future__ import annotations

from pathlib import Path

from ..config import DB_PATH_DEFAULT
from ..extraction.ocr_mark_normalizer import load_known_brands_from_db


class BrandKnowledgeBase:
    """Кэш брендов и полных обозначений из cable_marks."""

    def __init__(self, db_path: Path | str = DB_PATH_DEFAULT) -> None:
        self._db_path = Path(db_path)
        self._brands: set[str] | None = None
        self._full_marks: set[str] | None = None

    def brands(self) -> set[str]:
        if self._brands is None:
            self._brands = load_known_brands_from_db(self._db_path)
        return set(self._brands)

    def full_marks(self, *, limit: int = 500) -> set[str]:
        if self._full_marks is None:
            from ..persistence.sqlite_repo import list_cable_marks

            marks: set[str] = set()
            for row in list_cable_marks(limit=limit, db_path=self._db_path):
                mark = (row.get("mark") or row.get("designation") or "").strip()
                if mark and len(mark) >= 3:
                    marks.add(mark)
            self._full_marks = marks
        return set(self._full_marks)

    def reload(self) -> None:
        self._brands = None
        self._full_marks = None