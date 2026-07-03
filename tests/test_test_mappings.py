"""Тесты test_mappings: CRUD, расширенные фразы, алиасы кодов."""

from __future__ import annotations

import pytest

from request_processor.mapping.requirement_mapper import map_requirements_to_tests, resolve_test_code
from request_processor.persistence.sqlite_repo import (
    add_test_mapping,
    delete_test_mapping,
    init_db,
    list_test_mappings,
    sync_default_test_mappings,
    update_test_mapping,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mappings.db"
    init_db(path)
    return path


def test_sync_default_mappings_has_solar_phrases(db) -> None:
    sync_default_test_mappings(db)
    patterns = {row["requirement_pattern"] for row in list_test_mappings(db_path=db)}
    assert "воздействию солнечного" in patterns
    assert "метод 211-1" in patterns
    assert "электрическое сопротивление тпж" in patterns


def test_map_direction_phrase_solar(db) -> None:
    sync_default_test_mappings(db)
    text = "Стойкость к воздействию солнечного излучения (ГОСТ 20.57.406 метод 211-1)"
    suggestions = map_requirements_to_tests(text, db_path=db)
    codes = [s.code for s in suggestions]
    assert "solar_radiation" in codes


def test_map_voltage_phrase_uses_price_code(db) -> None:
    sync_default_test_mappings(db)
    suggestions = map_requirements_to_tests(
        "Провести испытание напряжением согласно ТУ",
        db_path=db,
    )
    codes = [s.code for s in suggestions]
    assert "испытание_напряжением" in codes


def test_resolve_test_code_alias(db) -> None:
    from request_processor.persistence.sqlite_repo import add_test_item
    from request_processor.models import TestItem

    add_test_item(
        TestItem(
            code="электрическое_сопротивление_тпж",
            name="Электрическое сопротивление ТПЖ",
            base_cost=400,
            category="НЧ",
            rule_type="per_core",
        ),
        db_path=db,
    )
    assert resolve_test_code("resistance_core", db) == "электрическое_сопротивление_тпж"


def test_crud_mapping(db) -> None:
    mapping_id = add_test_mapping("тестовая фраза уникальная", "solar_radiation", db_path=db)
    rows = list_test_mappings(db_path=db)
    assert any(r["id"] == mapping_id for r in rows)

    update_test_mapping(
        mapping_id,
        requirement_pattern="тестовая фраза обновлённая",
        note="pytest",
        db_path=db,
    )
    row = next(r for r in list_test_mappings(db_path=db) if r["id"] == mapping_id)
    assert row["requirement_pattern"] == "тестовая фраза обновлённая"
    assert row["note"] == "pytest"

    assert delete_test_mapping(mapping_id, db_path=db) is True
    assert not any(r["id"] == mapping_id for r in list_test_mappings(db_path=db))


def test_custom_mapping_used_in_mapper(db) -> None:
    add_test_mapping("стойкость к ультрафиолету", "humidity", note="custom", db_path=db)
    suggestions = map_requirements_to_tests(
        "Проверить стойкость к ультрафиолету на образце",
        db_path=db,
    )
    hit = next((s for s in suggestions if s.code == "humidity" and s.source == "database"), None)
    assert hit is not None
    assert hit.mapping_id is not None