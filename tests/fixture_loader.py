"""Загрузка эталонных JSON для регрессионных тестов.

Приоритет: `tests/fixtures/` (закреплённые в git) → `data/extracted/` (локально).
"""

from __future__ import annotations

import json
from pathlib import Path

from request_processor.extraction.pdf_extractor import build_search_text
from request_processor.models import PdfExtractionResult

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
EXTRACTED_DIR = Path(__file__).resolve().parents[1] / "data" / "extracted"

# Короткое имя в тестах → фактическое имя файла на диске (локально).
# Не используем в путях названия организаций/городов.
# Короткое имя → glob-паттерны локальных файлов (без названий организаций).
ALIASES: dict[str, list[str]] = {
    "direction_sample.json": ["direction_sample.json", "*Направление*ИЛ*.json"],
    "act_sample.json": ["act_sample.json", "*Акт отбора*.json"],
    "letter_lan_sample.json": ["letter_lan_sample.json", "*Письмо 145*.json"],
    "letter_periodic_sample.json": [
        "letter_periodic_sample.json",
        "*период*.json",
        "*Период*.json",
    ],
    "letter_marks_sample.json": [
        "letter_marks_sample.json",
        "*163*.json",
    ],
}


def resolve_fixture_path(name: str) -> Path:
    bundled = FIXTURES_DIR / name
    if bundled.is_file():
        return bundled

    patterns = ALIASES.get(name, [name])
    for pat in patterns:
        if any(ch in pat for ch in "*?[]"):
            matches = sorted(EXTRACTED_DIR.glob(pat))
            if matches:
                return matches[0]
        else:
            path = EXTRACTED_DIR / pat
            if path.is_file():
                return path
    path = EXTRACTED_DIR / name
    if path.is_file():
        return path
    raise FileNotFoundError(
        f"Фикстура {name!r} не найдена в {FIXTURES_DIR} или {EXTRACTED_DIR} "
        f"(паттерны: {patterns})"
    )


def load_extraction_fixture(name: str) -> PdfExtractionResult:
    path = resolve_fixture_path(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    return PdfExtractionResult.model_validate(data)


def fixture_search_text(result: PdfExtractionResult) -> str:
    return build_search_text(result.text, result.tables)
