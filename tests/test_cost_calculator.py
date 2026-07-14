"""Тесты калькулятора по шаблону прайса (Obsidian §39)."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.calculation.cost_calculator import (
    calculate_cost,
    normalize_test_quantities,
)
from request_processor.calculation.sample_complexity import compute_sample_complexity
from request_processor.calculation.test_rules import infer_rule_type
from request_processor.persistence.sqlite_repo import (
    build_default_hours_map,
    get_all_test_items,
    init_db,
    insert_test_item,
    migrate_db,
)
from request_processor.models import TestItem as PriceTestItem

CLIMATE_SLUG = "стойкость_к_солнечной_радиации"


@pytest.fixture()
def price_db(tmp_path: Path) -> Path:
    db = tmp_path / "price.db"
    init_db(db)
    insert_test_item(
        PriceTestItem(
            code="базовая_стоимость",
            name="Базовая стоимость",
            base_cost=15000,
            category="Административная работа",
            rule_type="fixed",
        ),
        db,
    )
    insert_test_item(
        PriceTestItem(
            code="базовая_подготовка_образцов",
            name="Базовая подготовка образцов",
            base_cost=300,
            category="Подготовка к испытаниям",
            rule_type="fixed",
        ),
        db,
    )
    insert_test_item(
        PriceTestItem(
            code="испытание_напряжением",
            name="Испытание напряжением",
            base_cost=400,
            category="Электрические параметры НЧ",
            rule_type="fixed",
        ),
        db,
    )
    insert_test_item(
        PriceTestItem(
            code=CLIMATE_SLUG,
            name="Стойкость к солнечной радиации",
            base_cost=3300,
            category="Внешние воздействующие факторы",
            rule_type="time_based",
            rule_params={
                "hours_key": "solar_radiation",
                "default_hours": 24.0,
                "cost_per_hour": 400.0,
            },
        ),
        db,
    )
    insert_test_item(
        PriceTestItem(
            code="измерение_затухания_оптического_волокнаодного",
            name="Измерение затухания оптического волокна (одного)",
            base_cost=500,
            category="Оптические параметры",
            rule_type="per_core",
        ),
        db,
    )
    # Устаревший EN-дубль — должен удалиться при migrate
    insert_test_item(
        PriceTestItem(
            code="solar_radiation",
            name="Стойкость к солнечной радиации (EN)",
            base_cost=400,
            category="Внешние воздействующие факторы",
            rule_type="time_based",
            rule_params={
                "hours_key": "solar_radiation",
                "default_hours": 24.0,
                "cost_per_hour": 400.0,
            },
        ),
        db,
    )
    migrate_db(db)
    return db


def test_normalize_test_quantities_merges_duplicates() -> None:
    assert normalize_test_quantities(["a", "a", "b"], {"b": 3}) == {"a": 2, "b": 3}


def test_optical_infer_per_core() -> None:
    rule, _ = infer_rule_type("Измерение затухания оптического волокна (одного)", "Оптические параметры")
    assert rule == "per_core"


def test_sample_complexity_armor_and_cores() -> None:
    mark = "ВВГнг(А) 12х16"
    coef, note = compute_sample_complexity(mark, has_armor=True)
    assert coef >= 2.0
    assert "броня" in note


def test_quantity_multiplies_fixed_test(price_db: Path) -> None:
    calc = calculate_cost(
        "ВВГ 3х2,5",
        ["испытание_напряжением"],
        db_path=price_db,
        quantities={"испытание_напряжением": 3},
        apply_minimum=False,
    )
    assert len(calc.lines) == 1
    assert calc.lines[0].quantity == 3
    assert calc.lines[0].final_cost == 1200.0


def test_minimum_order_applied(price_db: Path) -> None:
    calc = calculate_cost(
        "ВВГ 3х2,5",
        ["испытание_напряжением"],
        db_path=price_db,
        apply_minimum=True,
    )
    assert calc.total_cost_without_vat == 15000.0
    assert calc.minimum_adjustment == 14600.0


def test_climate_slug_resolves_from_en_code(price_db: Path) -> None:
    hours = build_default_hours_map(price_db)
    calc = calculate_cost("ВВГ 3х2,5", ["solar_radiation"], hours, price_db, apply_minimum=False)
    assert calc.lines[0].final_cost == 3300 + 400 * hours["solar_radiation"]
    codes = {item.code for item in get_all_test_items(price_db)}
    assert "solar_radiation" not in codes
    assert CLIMATE_SLUG in codes


def test_prep_complexity_multiplier(price_db: Path) -> None:
    calc = calculate_cost(
        "ВВГ 3х2,5",
        ["базовая_подготовка_образцов"],
        db_path=price_db,
        has_armor=True,
        apply_minimum=False,
    )
    assert calc.lines[0].final_cost == 300 * 1.5


def test_discount_percent(price_db: Path) -> None:
    calc = calculate_cost(
        "ВВГ 3х2,5",
        ["испытание_напряжением"],
        db_path=price_db,
        discount_percent=10,
        apply_minimum=False,
    )
    assert calc.total_cost_without_vat == 360.0