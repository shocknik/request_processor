"""Регрессия: адрес одного завода не подменяется адресом другого (периодика/Калуга)."""

from __future__ import annotations

from request_processor.extraction.organization_extractor import (
    _PERIODIC_FACTORY_POSTAL,
    _is_periodic_letter_factory,
    extract_manufacturer_details,
    extract_organizations,
    extract_periodic_factory_address,
    finalize_organization_address,
    sanitize_address,
)
from request_processor.models import OrganizationExtract

# Синтетическое направление: изготовитель — Тольятти, заказчик — ОС (не Калуга).
_TOLYATTI_DIRECTION = """
В испытательную лабораторию (ИЛ)
Испытательный центр Общества с ограниченной ответственностью НИЦ "Кабель-Тест"
РОСС RU.0001.21КБ32
107497, РОССИЯ, город Москва, ул. Бирюсинка, д. 6
НАПРАВЛЕНИЕ
образцов на испытание
Орган по сертификации Общества с ограниченной ответственностью «Центр электротехнических испытаний».
Место нахождения: 156019, Россия, Костромская область, город Кострома, улица Петра Щербины, дом 9.
Адрес места осуществления деятельности: 115093, Россия, город Москва, 1-й Щипковский переулок, дом 1.
Телефон: +7 4992816953. адрес электронной почты: info@ceticentr.ru.
направляет образцы (пробы) продукции
Кабель связи марки КСВПВ-5е 2x2x0,50
Изготовитель: ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ТОЛЬЯТТИНСКИЙ КАБЕЛЬНЫЙ ЗАВОД"
Место нахождения (адрес юридического лица): 445043, Россия, Самарская область, город Тольятти, улица Северная, здание 111, помещение 299
Адрес места осуществления деятельности по изготовлению продукции: 445043, Россия, Самарская область, город Тольятти, улица Северная, здание 111, помещение 299
(полное наименование изготовителя, адрес)
Цель проведения испытаний: сертификационные испытания
Серийный выпуск
"""


def test_tolyatti_not_treated_as_periodic_factory() -> None:
    name = 'ООО «ТОЛЬЯТТИНСКИЙ КАБЕЛЬНЫЙ ЗАВОД»'
    assert not _is_periodic_letter_factory(name)
    assert not _is_periodic_letter_factory(name, _TOLYATTI_DIRECTION)


def test_generic_cable_factory_is_periodic_name() -> None:
    assert _is_periodic_letter_factory('ООО «Кабельный завод»')
    assert _is_periodic_letter_factory("ООО «Калужский кабельный завод»")


def test_ceti_not_periodic_even_if_doc_mentions_cable_plant() -> None:
    assert not _is_periodic_letter_factory(
        "ООО «Центр электротехнических испытаний»",
        _TOLYATTI_DIRECTION,
    )


def test_extract_periodic_address_skips_tolyatti_direction() -> None:
    assert extract_periodic_factory_address(_TOLYATTI_DIRECTION) is None


def test_manufacturer_details_tolyatti_address() -> None:
    name, addr = extract_manufacturer_details(_TOLYATTI_DIRECTION)
    assert name
    assert "тольят" in name.lower()
    assert addr
    assert "445043" in addr
    assert "тольят" in addr.lower() or "северн" in addr.lower()
    if _PERIODIC_FACTORY_POSTAL:
        assert _PERIODIC_FACTORY_POSTAL not in addr
    assert "жилетово" not in addr.lower()
    assert "цель проведения" not in addr.lower()


def test_sanitize_strips_direction_labels_and_tail() -> None:
    blob = (
        "Место нахождения (адрес юридического лица): 445043, Россия, Самарская область, "
        "город Тольятти, улица Северная, здание 111, помещение 299 "
        "Адрес места осуществления деятельности по изготовлению продукции: 445043, … "
        "Цель проведения испытаний: сертификационные"
    )
    cleaned = sanitize_address(blob)
    assert cleaned
    assert cleaned.startswith("445043")
    assert "Место нахождения" not in cleaned
    assert "Цель проведения" not in cleaned


def test_extract_organizations_tolyatti_keeps_own_address() -> None:
    orgs = extract_organizations(_TOLYATTI_DIRECTION)
    mfg = next(o for o in orgs if o.role == "manufacturer")
    assert "тольят" in mfg.name.lower()
    assert mfg.address
    assert "445043" in (mfg.address or "")
    if _PERIODIC_FACTORY_POSTAL:
        assert _PERIODIC_FACTORY_POSTAL not in (mfg.address or "")
        assert not any(
            _PERIODIC_FACTORY_POSTAL in (o.address or "")
            for o in orgs
            if o.address
        )


def test_finalize_does_not_inject_kaluga_into_other_plant() -> None:
    org = OrganizationExtract(
        name='ООО «ТОЛЬЯТТИНСКИЙ КАБЕЛЬНЫЙ ЗАВОД»',
        address="445043, Россия, Самарская область, город Тольятти, улица Северная, здание 111",
        role="manufacturer",
    )
    fixed = finalize_organization_address(org, _TOLYATTI_DIRECTION)
    assert "445043" in (fixed.address or "")
    if _PERIODIC_FACTORY_POSTAL:
        assert _PERIODIC_FACTORY_POSTAL not in (fixed.address or "")


def test_finalize_empty_tolyatti_does_not_get_profile_address() -> None:
    org = OrganizationExtract(
        name='ООО «ТОЛЬЯТТИНСКИЙ КАБЕЛЬНЫЙ ЗАВОД»',
        role="manufacturer",
    )
    fixed = finalize_organization_address(org, _TOLYATTI_DIRECTION)
    if _PERIODIC_FACTORY_POSTAL:
        assert fixed.address is None or _PERIODIC_FACTORY_POSTAL not in (fixed.address or "")
    assert not fixed.address or "жилетово" not in (fixed.address or "").lower()
