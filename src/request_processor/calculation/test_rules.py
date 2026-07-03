"""
Определение rule_type испытаний по названию и категории (как в прайс-листе Excel).
"""

from __future__ import annotations

import re
from typing import Any

from .climatic_tests import CLIMATIC_CODES, CLIMATIC_TESTS

# Порядок категорий из «Обновленная стоимость на 2026 год.xlsx»
CATEGORY_ORDER: list[str] = [
    "Административная работа",
    "Подготовка к испытаниям",
    "Конструкция",
    "Физико-механические параметры",
    "Электрические параметры НЧ",
    "Электрические параметры ВЧ",
    "Оптические параметры",
    "Механические воздействия",
    "Внешние воздействующие факторы",
    "Пожарная безопасность",
]

CATEGORY_SHORT: dict[str, str] = {
    "Административная работа": "Админ",
    "Подготовка к испытаниям": "Подготовка",
    "Конструкция": "Конструкция",
    "Физико-механические параметры": "Физ.-мех.",
    "Электрические параметры НЧ": "Электр. НЧ",
    "Электрические параметры ВЧ": "Электр. ВЧ",
    "Оптические параметры": "Оптика",
    "Механические воздействия": "Механика",
    "Внешние воздействующие факторы": "Климатика",
    "Пожарная безопасность": "Пожарная",
}

CATEGORY_COLORS: dict[str, str] = {
    "Административная работа": "#f1f5f9",
    "Подготовка к испытаниям": "#fef3c7",
    "Конструкция": "#e0f2fe",
    "Физико-механические параметры": "#fce7f3",
    "Электрические параметры НЧ": "#dbeafe",
    "Электрические параметры ВЧ": "#c7d2fe",
    "Оптические параметры": "#d1fae5",
    "Механические воздействия": "#ffedd5",
    "Внешние воздействующие факторы": "#eff6ff",
    "Пожарная безопасность": "#fee2e2",
}

_PER_GROUP_KEYWORDS = (
    "емкост",
    "индуктивн",
    "затухан",
    "волнов",
)

_PER_CORE_KEYWORDS = (
    "сопротивлен",
)

# Сопротивления ВЧ на пару/связь — per_group
_PER_GROUP_RESISTANCE_HINTS = (
    "связи",
    "экранирован",
    "излучен",
)


def _climatic_spec_by_code(code: str) -> dict[str, Any] | None:
    for spec in CLIMATIC_TESTS:
        if spec["code"] == code:
            return spec
    return None


_CLIMATIC_MARKERS: list[tuple[str, str]] = [
    ("пониженной температуре", "temp_low"),
    ("повышенной температуре", "temp_high"),
    ("изменению температур", "temp_cycling"),
    ("повышенной влажности", "humidity"),
    ("солнечной радиации", "solar_radiation"),
]


def _match_climatic(name: str, category: str | None = None) -> dict[str, Any] | None:
    name_l = name.lower()
    cat_l = (category or "").lower()
    is_climatic_context = (
        "внешние воздействующие" in cat_l
        or name_l.startswith("стойкость")
        or name_l.startswith("выдержка")
    )
    if not is_climatic_context:
        return None
    for marker, code in _CLIMATIC_MARKERS:
        if marker in name_l:
            spec = _climatic_spec_by_code(code)
            if spec:
                return spec
    return None


def infer_rule_type(
    name: str,
    category: str | None = None,
    code: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Возвращает (rule_type, rule_params).

    - per_core: электрические сопротивления × количество жил
    - per_group: ёмкость, индуктивность, затухание, волновое × количество пар
    - time_based: климатические испытания
    - fixed: остальное
    """
    if code and code in CLIMATIC_CODES:
        spec = _climatic_spec_by_code(code)
        if spec:
            return "time_based", {
                "hours_key": spec["hours_key"],
                "default_hours": spec["default_hours"],
                "cost_per_hour": spec["cost_per_hour"],
            }

    name_l = name.lower()
    cat_l = (category or "").lower()

    spec = _match_climatic(name, category)
    if spec:
        return "time_based", {
            "hours_key": spec["hours_key"],
            "default_hours": spec["default_hours"],
            "cost_per_hour": spec["cost_per_hour"],
        }

    if any(k in name_l for k in _PER_GROUP_KEYWORDS):
        return "per_group", {}

    if any(k in name_l for k in _PER_CORE_KEYWORDS):
        if any(h in name_l for h in _PER_GROUP_RESISTANCE_HINTS):
            return "per_group", {}
        return "per_core", {}

    return "fixed", {}


def rule_type_label(rule_type: str) -> str:
    return {
        "fixed": "фикс",
        "per_core": "× жилы",
        "per_group": "× пары",
        "time_based": "⏱ часы",
    }.get(rule_type, rule_type)


def category_sort_key(category: str | None) -> tuple[int, str]:
    cat = (category or "Без категории").strip()
    if cat in CATEGORY_ORDER:
        return (CATEGORY_ORDER.index(cat), cat)
    return (len(CATEGORY_ORDER), cat)


DEFAULT_PRICE_XLSX = "data/Обновленная стоимость на 2026 год.xlsx"