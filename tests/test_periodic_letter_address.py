"""Адрес производителя в письме на периодические испытания."""

from __future__ import annotations

import pytest

from request_processor.extraction.letter_extractor import organizations_from_letter
from request_processor.extraction.organization_extractor import (
    _PERIODIC_FACTORY_CANONICAL_ADDRESS,
    _PERIODIC_FACTORY_POSTAL,
    extract_periodic_factory_address,
    sanitize_address,
)
from request_processor.models import OrganizationExtract
from request_processor.extraction.organization_extractor import finalize_organization_address

from tests.fixture_loader import load_extraction_fixture


def _periodic_letter_text() -> str:
    return load_extraction_fixture("letter_periodic_sample.json").text


def _require_local_profile() -> None:
    if not _PERIODIC_FACTORY_POSTAL or not _PERIODIC_FACTORY_CANONICAL_ADDRESS:
        pytest.skip("Нужен data/client_profiles.local.yaml (periodic_factory)")


def test_periodic_factory_address_from_ocr_header() -> None:
    _require_local_profile()
    text = _periodic_letter_text()
    addr = extract_periodic_factory_address(text)
    assert addr
    assert _PERIODIC_FACTORY_POSTAL in addr


def test_periodic_customer_org_has_normalized_address() -> None:
    _require_local_profile()
    text = _periodic_letter_text()
    orgs = organizations_from_letter(text)
    customer = next(o for o in orgs if o.role == "customer")
    assert customer.address
    assert _PERIODIC_FACTORY_POSTAL in (customer.address or "")


def test_latin_address_is_normalized() -> None:
    _require_local_profile()
    # Synthetic latin OCR noise; profile supplies expected postal
    latin = (
        f"{_PERIODIC_FACTORY_POSTAL}, Poccumickaa Peaepauna, region, district, "
        "A. settlement, YA. street, A. 1, CTP. 5, 1"
    )
    org = OrganizationExtract(
        name="ООО «Кабельный завод»",
        address=latin,
        role="customer",
    )
    fixed = finalize_organization_address(org, latin)
    assert fixed.address
    assert "Poccumickaa" not in (fixed.address or "")


def test_cable_marks_are_not_accepted_as_address() -> None:
    blob = """ВВГ-Пнг(А) 3х4ок (N, PE)-0,66
ПВСнг(А)-LS 3х2,50
АПуВ 1х6
ПБГВВ 2х1,5"""
    assert sanitize_address(blob) is None
