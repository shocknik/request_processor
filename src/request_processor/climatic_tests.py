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


def is_climatic_code(code: str) -> bool:
    return code in CLIMATIC_CODES


def climatic_settings_fields() -> list[tuple[str, str]]:
    """(ключ в настройках, подпись в GUI)."""
    return [
        ("temp_low", "Пониженная температура"),
        ("temp_high", "Повышенная температура"),
        ("temp_cycling", "Изменение температур"),
        ("humidity", "Повышенная влажность"),
        ("solar_radiation", "Солнечная радиация"),
    ]