"""Адрес заказчика в письме Калужского кабельного завода."""

from __future__ import annotations

from request_processor.extraction.letter_extractor import organizations_from_letter
from request_processor.extraction.organization_extractor import (
    extract_kaluga_factory_address,
    sanitize_address,
)

from tests.fixture_loader import load_extraction_fixture


def _kaluga_letter_text() -> str:
    return load_extraction_fixture("Письмо на период. исп. от 04.05.26.json").text

_EXPECTED_PARTS = (
    "249841",
    "Калужская область",
    "Дзержинский район",
    "Жилетово",
    "Промышленная",
    "д. 1",
    "стр. 5",
)


def test_kaluga_factory_address_from_ocr_header() -> None:
    text = _kaluga_letter_text()
    addr = extract_kaluga_factory_address(text)
    assert addr
    for part in _EXPECTED_PARTS:
        assert part in addr, f"нет {part!r} в {addr!r}"


def test_kaluga_customer_org_has_normalized_address() -> None:
    text = _kaluga_letter_text()
    orgs = organizations_from_letter(text)
    customer = next(o for o in orgs if o.role == "customer")
    assert customer.address
    assert "Калужская область" in customer.address
    assert "Промышленная" in customer.address


def test_latin_kaluga_address_is_normalized() -> None:
    from request_processor.extraction.organization_extractor import finalize_organization_address
    from request_processor.models import OrganizationExtract

    latin = (
        "249841, Poccumickaa Peaepauna, KaAyKCKaA OOACCTE, A3@PXXUHCKMM PANOH, "
        "A. Kuaetoso, YA. MpOMbiLuAeHHas, A. 1, CTP. 5, 1"
    )
    org = OrganizationExtract(
        name='ООО «Калужский кабельный завод»',
        address=latin,
        role="customer",
    )
    fixed = finalize_organization_address(org, latin)
    assert fixed.address
    assert "Калужская область" in fixed.address
    assert "Жилетово" in fixed.address
    assert "Промышленная" in fixed.address
    assert "Poccumickaa" not in fixed.address
    assert "Киевск" not in fixed.address


def test_wrong_kievsky_kaluga_address_is_corrected() -> None:
    from request_processor.extraction.organization_extractor import finalize_organization_address
    from request_processor.models import OrganizationExtract

    wrong = (
        "249841, Калужская область, Дзержинский район, "
        "п. Киевский, ул. Промышленная, д. 1, стр. 5"
    )
    org = OrganizationExtract(
        name='ООО «Калужский кабельный завод»',
        address=wrong,
        role="customer",
    )
    fixed = finalize_organization_address(org, _kaluga_letter_text())
    assert fixed.address
    assert "Жилетово" in fixed.address
    assert "Киевск" not in fixed.address


def test_cable_marks_are_not_accepted_as_address() -> None:
    blob = """ВВГ-Пнг(А) 3х4ок (N, PE)-0,66
ПВСнг(А)-LS 3х2,50
АПуВ 1х6
ПБГВВ 2х1,5"""
    assert sanitize_address(blob) is None