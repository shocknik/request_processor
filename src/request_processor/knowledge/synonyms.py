"""
Синонимы испытаний: разные формулировки ТУ/заявок → canonical test_items.code.

Загрузка: data/knowledge/manufacturer_v1/test_synonyms.yaml
Используется requirement_mapper и ассистентом (не для подстановки «из воздуха»).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT

DEFAULT_SYNONYMS_PATH = (
    PROJECT_ROOT / "data" / "knowledge" / "manufacturer_v1" / "test_synonyms.yaml"
)


@lru_cache(maxsize=2)
def load_test_synonyms(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_SYNONYMS_PATH
    if not p.is_file():
        return {"synonyms": [], "code_aliases": {}}
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {"synonyms": [], "code_aliases": {}}
    except Exception:
        return {"synonyms": [], "code_aliases": {}}


def resolve_test_phrase(phrase: str, *, path: str | None = None) -> tuple[str | None, float]:
    """
    Возвращает (canonical_code, confidence) или (None, 0).

    Сопоставление: нормализованное вхождение phrase ⊆ synonym или наоборот.
    """
    raw = (phrase or "").strip().lower()
    if not raw:
        return None, 0.0
    data = load_test_synonyms(path)
    best: tuple[str | None, float] = (None, 0.0)
    for row in data.get("synonyms") or []:
        if not isinstance(row, dict):
            continue
        syn = str(row.get("phrase") or "").strip().lower()
        code = str(row.get("canonical_code") or "").strip()
        conf = float(row.get("confidence") or 0.7)
        if not syn or not code:
            continue
        if syn in raw or raw in syn:
            if conf > best[1]:
                best = (code, conf)
    return best


def canonical_code_alias(code: str, *, path: str | None = None) -> str:
    """Разворачивает code_aliases (humidity → кириллический slug прайса)."""
    data = load_test_synonyms(path)
    aliases = data.get("code_aliases") or {}
    if not isinstance(aliases, dict):
        return code
    return str(aliases.get(code, code))
