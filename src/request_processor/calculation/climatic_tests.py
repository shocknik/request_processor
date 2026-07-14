"""
Константы и утилиты для климатических испытаний (time_based).
"""

from __future__ import annotations

from typing import TypedDict


class ClimaticTestDef(TypedDict):
    code: str
    name: str
    hours_key: str
    default_hours: float
    base_cost: float
    cost_per_hour: float


CLIMATIC_TESTS: list[ClimaticTestDef] = [
    {
        "code": "temp_low",
        "name": "Стойкость к пониженной температуре",
        "hours_key": "temp_low",
        "default_hours": 2.0,
        "base_cost": 350.0,
        "cost_per_hour": 350.0,
    },
    {
        "code": "temp_high",
        "name": "Стойкость к повышенной температуре",
        "hours_key": "temp_high",
        "default_hours": 2.0,
        "base_cost": 250.0,
        "cost_per_hour": 250.0,
    },
    {
        "code": "temp_cycling",
        "name": "Стойкость к изменению температур (резкое/плавное)",
        "hours_key": "temp_cycling",
        "default_hours": 2.0,
        "base_cost": 350.0,
        "cost_per_hour": 350.0,
    },
    {
        "code": "humidity",
        "name": "Стойкость к повышенной влажности воздуха",
        "hours_key": "humidity",
        "default_hours": 48.0,
        "base_cost": 300.0,
        "cost_per_hour": 300.0,
    },
    {
        "code": "solar_radiation",
        "name": "Стойкость к солнечной радиации",
        "hours_key": "solar_radiation",
        "default_hours": 24.0,
        "base_cost": 400.0,
        "cost_per_hour": 400.0,
    },
]

CLIMATIC_CODES = frozenset(t["code"] for t in CLIMATIC_TESTS)
CLIMATIC_HOURS_KEYS = frozenset(t["hours_key"] for t in CLIMATIC_TESTS)

# Канонические slug-коды в test_items (EN-коды — только ключи часов, не позиции прайса).
CLIMATE_SLUG_BY_HOURS_KEY: dict[str, str] = {
    "temp_low": "стойкость_к_пониженной_температуре",
    "temp_high": "стойкость_к_повышенной_температуре",
    "temp_cycling": "стойкость_к_изменению_температуррезкоеплавное",
    "humidity": "стойкость_к_повышенной_влажности_воздуха",
    "solar_radiation": "стойкость_к_солнечной_радиации",
}

# Устаревшие EN-коды test_items → slug (после миграции прайса).
CLIMATE_ITEM_ALIASES: dict[str, str] = dict(CLIMATE_SLUG_BY_HOURS_KEY)

# Обратный индекс: slug → hours_key (для часов выдержки).
HOURS_KEY_BY_CLIMATE_SLUG: dict[str, str] = {
    slug: key for key, slug in CLIMATE_SLUG_BY_HOURS_KEY.items()
}

# EN-дубли, удаляемые из test_items.
DEPRECATED_CLIMATE_ITEM_CODES = frozenset(CLIMATIC_CODES)


def is_climatic_code(code: str) -> bool:
    return code in CLIMATIC_CODES or code in HOURS_KEY_BY_CLIMATE_SLUG


def resolve_climate_item_code(code: str) -> str:
    """Приводит EN-код или hours_key к slug test_items."""
    return CLIMATE_ITEM_ALIASES.get(code, code)


def climatic_spec_for_item(code: str, rule_params: dict | None = None) -> ClimaticTestDef | None:
    """Спека климатики по slug или hours_key из rule_params."""
    params = rule_params or {}
    hours_key = params.get("hours_key") or HOURS_KEY_BY_CLIMATE_SLUG.get(code) or code
    for spec in CLIMATIC_TESTS:
        if spec["hours_key"] == hours_key or spec["code"] == code:
            return spec
    return None


def climatic_settings_fields() -> list[tuple[str, str]]:
    """(ключ в настройках, подпись в GUI)."""
    return [
        ("temp_low", "Пониженная температура"),
        ("temp_high", "Повышенная температура"),
        ("temp_cycling", "Изменение температур"),
        ("humidity", "Повышенная влажность"),
        ("solar_radiation", "Солнечная радиация"),
    ]