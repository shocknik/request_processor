"""Поиск файлов OCR-кэша (имя зависит от DPI и версии preprocess)."""

from __future__ import annotations

from pathlib import Path

OCR_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "ocr_cache"


def resolve_ocr_cache(*stem_parts: str) -> Path:
    """
    Находит файл кэша по подстрокам в имени (без учёта dpi/preprocess).

    Пример: resolve_ocr_cache('145', '02.02.2026')
    """
    if not OCR_CACHE_DIR.is_dir():
        raise FileNotFoundError(f"Каталог OCR-кэша не найден: {OCR_CACHE_DIR}")

    needles = [p.lower() for p in stem_parts if p]
    matches = [
        path
        for path in sorted(OCR_CACHE_DIR.glob("*.txt"))
        if all(n in path.name.lower() for n in needles)
    ]
    if not matches:
        raise FileNotFoundError(
            f"OCR-кэш не найден для {stem_parts!r} в {OCR_CACHE_DIR}"
        )
    return matches[0]