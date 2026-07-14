"""Smoke-тесты extract_organizations на эталонных JSON."""

from __future__ import annotations

import re

import pytest

from request_processor.extraction.organization_extractor import (
    extract_organizations,
    normalize_org_name,
    pick_customer_name,
    pick_manufacturer_name,
    _is_non_customer_org,
)

from tests.fixture_loader import fixture_search_text, load_extraction_fixture


def _norm_name(name: str) -> str:
    return normalize_org_name(name)


@pytest.mark.parametrize(
    "fixture_name,customer_fragment,manufacturer_fragment,min_orgs",
    [
        (
            "letter_periodic_sample.json",
            "кабельн",
            "кабельн",
            2,
        ),
        (
            "letter_lan_sample.json",
            "нпп",
            None,
            1,
        ),
        (
            "direction_sample.json",
            "кирскабель",
            "кирскабель",
            2,
        ),
        (
            "act_sample.json",
            "кирскабель",
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
    result = load_extraction_fixture("direction_sample.json")
    orgs = extract_organizations(fixture_search_text(result))
    roles = {org.role for org in orgs}
    assert "customer" in roles
    assert "manufacturer" in roles
    customer = pick_customer_name(orgs)
    assert "кирскабель" in _norm_name(customer)
    assert not _is_non_customer_org(next(o for o in orgs if o.name == customer))
    assert any(o.org_type == "testing_center" for o in orgs)
    assert any(o.org_type == "certification_body" for o in orgs)


def test_extract_organizations_empty_text() -> None:
    assert extract_organizations("") == []
    assert extract_organizations("   ") == []


def test_letter_145_customer_not_testing_center() -> None:
    result = load_extraction_fixture("letter_lan_sample.json")
    orgs = extract_organizations(fixture_search_text(result))
    customer = pick_customer_name(orgs)
    assert customer  # lab must not be customer
    assert "спецкабель" in _norm_name(customer)
    assert not _is_non_customer_org(next(o for o in orgs if o.name == customer))


def test_periodic_letter_factory_name_not_ocr_garbage() -> None:
    result = load_extraction_fixture("letter_periodic_sample.json")
    orgs = extract_organizations(fixture_search_text(result))
    customer = pick_customer_name(orgs)
    assert "кабельн" in _norm_name(customer)
    assert "завод" in _norm_name(customer)
    assert "o6gl" not in _norm_name(customer)