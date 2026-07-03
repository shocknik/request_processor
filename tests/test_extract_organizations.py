"""Smoke-тесты extract_organizations на эталонных JSON."""

from __future__ import annotations

import re

import pytest

from request_processor.extraction.organization_extractor import (
    extract_organizations,
    normalize_org_name,
    pick_customer_name,
    pick_manufacturer_name,
)

from tests.fixture_loader import fixture_search_text, load_extraction_fixture


def _norm_name(name: str) -> str:
    return normalize_org_name(name)


@pytest.mark.parametrize(
    "fixture_name,customer_fragment,manufacturer_fragment,min_orgs",
    [
        (
            "Письмо на период. исп. от 04.05.26.json",
            "калужск",
            None,
            1,
        ),
        (
            "Письмо 145 от 02.02.2026 .json",
            "спецкабель",
            None,
            1,
        ),
        (
            "27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json",
            "тест-с",
            "кирскабель",
            2,
        ),
        (
            "27_1-2-2026 Акт отбора 10094807(1).json",
            "тест-с",
            None,
            1,
        ),
    ],
)
def test_extract_organizations_on_fixtures(
    fixture_name: str,
    customer_fragment: str,
    manufacturer_fragment: str | None,
    min_orgs: int,
) -> None:
    result = load_extraction_fixture(fixture_name)
    orgs = extract_organizations(fixture_search_text(result))

    assert len(orgs) >= min_orgs
    customer = pick_customer_name(orgs)
    assert customer_fragment in _norm_name(customer)

    if manufacturer_fragment:
        manufacturer = pick_manufacturer_name(orgs)
        assert manufacturer_fragment in _norm_name(manufacturer)


def test_extract_organizations_roles_direction() -> None:
    result = load_extraction_fixture("27_1-2-2026 Направление в ИЛ 10094807 Кабель-Тест.json")
    orgs = extract_organizations(fixture_search_text(result))
    roles = {org.role for org in orgs}
    assert "customer" in roles
    assert "manufacturer" in roles


def test_extract_organizations_empty_text() -> None:
    assert extract_organizations("") == []
    assert extract_organizations("   ") == []


def test_letter_145_customer_not_testing_center() -> None:
    result = load_extraction_fixture("Письмо 145 от 02.02.2026 .json")
    customer = pick_customer_name(extract_organizations(fixture_search_text(result)))
    assert "кабель-тест" not in _norm_name(customer)
    assert re.search(r"спецкабель", _norm_name(customer))