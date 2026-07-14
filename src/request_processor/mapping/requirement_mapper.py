"""
Маппинг текста требований из заявки на коды испытаний (test_items.code).

Rule engine v1: встроенные правила + таблица test_mappings в БД.
ИИ-маппер — опционально поверх (фаза 2+, см. Obsidian §27).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..models import CableMarkMatch, TestSuggestion

MappingSource = Literal["builtin", "database"]


@dataclass(frozen=True)
class _MappingRule:
    pattern: str
    test_code: str
    confidence: float
    note: str | None = None
    is_regex: bool = False


from ..calculation.climatic_tests import CLIMATE_ITEM_ALIASES

# Устаревшие slug → коды из прайса (test_items).
_CODE_ALIASES: dict[str, str] = {
    "resistance_core": "электрическое_сопротивление_тпж",
    "insulation_resistance": "электрическое_сопротивление_изоляции_тпж",
    "voltage_test": "испытание_напряжением",
    "capacitance": "измерение_емкостииндуктивности",
    "inductance": "измерение_емкостииндуктивности",
    "attenuation": "измерение_затухания_экранирования",
    **CLIMATE_ITEM_ALIASES,
}

# Порядок: более специфичные фразы выше. Проверка — по вхождению в нижний регистр.
_BUILTIN_RULES: tuple[_MappingRule, ...] = (
    _MappingRule("воздействию солнечного", "стойкость_к_солнечной_радиации", 0.93, "Направления в ИЛ"),
    _MappingRule("солнечного излучения", "стойкость_к_солнечной_радиации", 0.92, "ГОСТ 20.57.406"),
    _MappingRule("солнечной радиации", "стойкость_к_солнечной_радиации", 0.92),
    _MappingRule("20.57.406", "стойкость_к_солнечной_радиации", 0.88, "ГОСТ солнечного излучения"),
    _MappingRule("метод 211-1", "стойкость_к_солнечной_радиации", 0.86),
    _MappingRule("ультрафиолет", "стойкость_к_солнечной_радиации", 0.78, "УФ"),
    _MappingRule("повышенной влажности", "стойкость_к_повышенной_влажности_воздуха", 0.90),
    _MappingRule("влажности воздуха", "стойкость_к_повышенной_влажности_воздуха", 0.88),
    _MappingRule("влажност", "стойкость_к_повышенной_влажности_воздуха", 0.75),
    _MappingRule("пониженной температур", "стойкость_к_пониженной_температуре", 0.90),
    _MappingRule("отрицательной температур", "стойкость_к_пониженной_температуре", 0.85),
    _MappingRule("повышенной температур", "стойкость_к_повышенной_температуре", 0.90),
    _MappingRule("изменению температур", "стойкость_к_изменению_температуррезкоеплавное", 0.88),
    _MappingRule("циклическ", "стойкость_к_изменению_температуррезкоеплавное", 0.70),
    _MappingRule("простому изгибу", "стойкость_к_простому_изгибу_100_циклов", 0.82),
    _MappingRule("огнестойк", "огнестойкость", 0.85),
    _MappingRule(
        "электрическое сопротивление тпж",
        "электрическое_сопротивление_тпж",
        0.90,
    ),
    _MappingRule(r"сопротивлен\w*\s+изоляц", "электрическое_сопротивление_изоляции_тпж", 0.88, is_regex=True),
    _MappingRule("сопротивлен", "электрическое_сопротивление_тпж", 0.80, is_regex=True),
    _MappingRule("изоляц", "электрическое_сопротивление_изоляции_тпж", 0.72),
    _MappingRule("испытание напряжением", "испытание_напряжением", 0.90),
    _MappingRule("напряжени", "испытание_напряжением", 0.75),
    _MappingRule("емкост", "измерение_емкостииндуктивности", 0.80),
    _MappingRule("индуктивн", "измерение_емкостииндуктивности", 0.80),
    _MappingRule("затухания экранирования", "измерение_затухания_экранирования", 0.85),
    _MappingRule("затухан", "измерение_затухания_экранирования", 0.78),
)


def _normalize_requirements(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def resolve_test_code(code: str, db_path: str | Path | None = None) -> str:
    """
    Подбирает код испытания, существующий в test_items.

    Сначала исходный code, затем алиас из _CODE_ALIASES.
    """
    if db_path is None:
        return code
    from ..persistence.sqlite_repo import get_test_item_by_code

    if get_test_item_by_code(code, db_path):
        return code
    alias = _CODE_ALIASES.get(code)
    if alias and get_test_item_by_code(alias, db_path):
        return alias
    return code


def _match_builtin(text: str) -> list[tuple[str, float, str | None, str]]:
    """Возвращает (test_code, confidence, note, matched_pattern)."""
    hits: dict[str, tuple[float, str | None, str]] = {}
    for rule in _BUILTIN_RULES:
        if rule.test_code == "электрическое_сопротивление_тпж" and "изоляц" in text:
            continue
        matched = False
        matched_pat = rule.pattern
        if rule.is_regex:
            m = re.search(rule.pattern, text, re.IGNORECASE)
            matched = m is not None
            if m:
                matched_pat = m.group(0)
        else:
            matched = rule.pattern in text
        if not matched:
            continue
        prev = hits.get(rule.test_code)
        if prev is None or rule.confidence > prev[0]:
            hits[rule.test_code] = (rule.confidence, rule.note, matched_pat)
    return [(code, conf, note, pat) for code, (conf, note, pat) in hits.items()]


def _match_database(
    text: str,
    db_path: str | Path,
) -> list[tuple[str, float, str | None, str, int]]:
    from ..persistence.sqlite_repo import list_test_mappings

    hits: dict[str, tuple[float, str | None, str, int]] = {}
    for row in list_test_mappings(db_path=db_path):
        pattern = (row.get("requirement_pattern") or "").lower()
        if not pattern or pattern not in text:
            continue
        code = row["test_code"]
        usage = int(row.get("usage_count") or 0)
        conf = min(0.95, 0.80 + min(usage, 10) * 0.01)
        prev = hits.get(code)
        if prev is None or conf > prev[0]:
            hits[code] = (conf, row.get("note"), pattern, row["id"])
    return [
        (code, conf, note, pat, row_id)
        for code, (conf, note, pat, row_id) in hits.items()
    ]


def _resolve_test_name(code: str, db_path: str | Path | None) -> str:
    if db_path is not None:
        from ..persistence.sqlite_repo import get_test_item_by_code

        item = get_test_item_by_code(code, db_path)
        if item:
            return item.name
    from ..calculation.climatic_tests import CLIMATIC_TESTS

    for spec in CLIMATIC_TESTS:
        if spec["code"] == code:
            return spec["name"]
    return code


def map_requirements_to_tests(
    requirements_text: str | None,
    *,
    db_path: str | Path | None = None,
) -> list[TestSuggestion]:
    """
    Сопоставляет сырой текст требований со списком предлагаемых испытаний.

    Объединяет встроенные правила и записи test_mappings; дедупликация по code.
    """
    text = _normalize_requirements(requirements_text)
    if not text:
        return []

    merged: dict[str, TestSuggestion] = {}

    # Knowledge base synonyms (data/knowledge/…/test_synonyms.yaml)
    try:
        from ..knowledge.synonyms import resolve_test_phrase

        kb_code, kb_conf = resolve_test_phrase(text)
        if kb_code and kb_conf >= 0.75:
            resolved = resolve_test_code(kb_code, db_path)
            merged[resolved] = TestSuggestion(
                code=resolved,
                name=_resolve_test_name(resolved, db_path),
                confidence=kb_conf,
                source="knowledge_synonym",
                matched_pattern=text[:120],
                note="KB test_synonyms",
            )
    except Exception:
        pass

    for code, conf, note, pattern in _match_builtin(text):
        resolved = resolve_test_code(code, db_path)
        merged[resolved] = TestSuggestion(
            code=resolved,
            name=_resolve_test_name(resolved, db_path),
            confidence=conf,
            source="builtin",
            matched_pattern=pattern,
            note=note,
        )

    if db_path is not None:
        for code, conf, note, pattern, mapping_id in _match_database(text, db_path):
            resolved = resolve_test_code(code, db_path)
            existing = merged.get(resolved)
            if existing is None or conf > existing.confidence:
                merged[resolved] = TestSuggestion(
                    code=resolved,
                    name=_resolve_test_name(resolved, db_path),
                    confidence=conf,
                    source="database",
                    matched_pattern=pattern,
                    note=note,
                    mapping_id=mapping_id,
                )

    return sorted(merged.values(), key=lambda s: (-s.confidence, s.code))


def suggest_tests_for_mark(
    match: CableMarkMatch,
    *,
    db_path: str | Path | None = None,
) -> list[TestSuggestion]:
    """Предлагает испытания для одной марки по requirements_raw и контексту."""
    parts = [match.requirements_raw, match.context, match.document]
    blob = " ".join(p for p in parts if p)
    return map_requirements_to_tests(blob, db_path=db_path)