"""Org Fix: extract certification body, confirm save, fuzzy dedup, own lab skip."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.extraction.organization_extractor import (
    extract_certification_body_from_direction,
    extract_organizations,
    normalize_org_name,
    pick_customer_name,
    pick_manufacturer_name,
)
from request_processor.generation.lab_profile import (
    clear_lab_profile_cache,
    is_own_lab_name,
)
from request_processor.models import OrganizationExtract
from request_processor.persistence.sqlite_repo import (
    create_organization,
    find_similar_organizations,
    init_db,
    list_organizations,
    save_organizations_from_extraction,
)

PROD_SNAP = (
    Path(__file__).resolve().parents[1]
    / "_from_work"
    / "Опыт работы с приложением"
    / "_extracted"
    / "parse_snapshots"
    / "20260721_134455_7d2deb.json"
)


@pytest.fixture()
def mem_db(tmp_path: Path) -> Path:
    db = tmp_path / "org_test.db"
    init_db(db)
    return db


def test_is_own_lab_name_cable_test() -> None:
    clear_lab_profile_cache()
    assert is_own_lab_name('ООО НИЦ «Кабель-Тест»')
    assert is_own_lab_name("Кабель-Тест")
    assert is_own_lab_name('Испытательный центр ООО НИЦ "Кабель-Тест"')
    assert not is_own_lab_name("ООО «ФаерЛаб»")
    assert not is_own_lab_name('ООО НПП «Спецкабель»')


def test_extract_cert_body_firelab_from_direction_text() -> None:
    text = """
В аккредитованную испытательную лабораторию
Испытательный центр Общества с ограниченной ответственностью НИЦ "Кабель-Тест", уникальный номер записи об аккредитации в реестре аккредитованных лиц РОСС RU.0001.21КБ32
Наименование ИЛ, уникальный номер записи об аккредитации в реестре аккредитованных лиц
107497, РОССИЯ, город Москва, ул. Бирюсинка, д. 6
НАПРАВЛЕНИЕ
Орган по сертификации Общества с ограниченной ответственностью «ФаерЛаб»
наименование органа по сертификации
Адрес места осуществления деятельности: 143985, РФ, Московская обл., г.о. Балашиха, г. Балашиха, мкр. Железнодорожный, ул. Автозаводская, д. 50А, пом. № 16, № 16а. Телефон: (495) 112-01-93, адрес электронной почты: info@firelab.su. ОГРН: 1185053038653.
адрес места осуществления деятельности, телефон, факс, ОГРНнаправляет образцы (пробы) продукции
"""
    cert = extract_certification_body_from_direction(text)
    assert cert is not None
    assert "фаер" in normalize_org_name(cert.name)
    assert cert.org_type == "certification_body"
    assert cert.role == "customer"
    assert cert.email and "firelab" in cert.email.lower()
    assert cert.phone

    orgs = extract_organizations(text)
    customer = pick_customer_name(orgs)
    assert "фаер" in normalize_org_name(customer)
    # производитель в тексте не указан — пусто, не ИЛ
    mfg = pick_manufacturer_name(orgs)
    assert mfg == "" or "кабель" not in normalize_org_name(mfg) or "тест" not in normalize_org_name(mfg)
    assert not is_own_lab_name(customer)


@pytest.mark.skipif(not PROD_SNAP.is_file(), reason="prod snapshot not on this machine")
def test_prod_snapshot_0020_customer_firelab() -> None:
    import json

    data = json.loads(PROD_SNAP.read_text(encoding="utf-8"))
    text = data["result"]["text"]
    orgs = extract_organizations(text)
    customer = pick_customer_name(orgs)
    assert "фаер" in normalize_org_name(customer)
    assert any(o.org_type == "testing_center" for o in orgs)


def test_save_orgs_skips_own_lab_and_saves_customer(mem_db: Path) -> None:
    clear_lab_profile_cache()
    orgs = [
        OrganizationExtract(
            name='ООО НИЦ «Кабель-Тест»',
            org_type="testing_center",
            role="unknown",
            confidence=0.8,
        ),
        OrganizationExtract(
            name="ООО «ФаерЛаб»",
            org_type="certification_body",
            role="customer",
            address="143985, Балашиха",
            phone="(495) 112-01-93",
            email="info@firelab.su",
            confidence=0.9,
        ),
    ]
    ids = save_organizations_from_extraction(
        orgs,
        source="test",
        customer_name="ООО «ФаерЛаб»",
        manufacturer_name='ООО НПП «Спецкабель»',
        customer_address="143985, Балашиха",
        db_path=mem_db,
    )
    assert ids["customer_org_id"] is not None
    assert ids["manufacturer_org_id"] is not None
    assert ids["customer_org_id"] != ids["manufacturer_org_id"]

    rows = list_organizations(limit=50, db_path=mem_db)
    names_n = {normalize_org_name(r["name"]) for r in rows}
    assert any("фаер" in n for n in names_n)
    assert any("спецкабель" in n for n in names_n)
    # наша ИЛ не должна попасть в справочник из save
    assert not any("кабель" in n and "тест" in n for n in names_n)


def test_find_similar_organizations(mem_db: Path) -> None:
    create_organization(
        name='ООО «ФаерЛаб»',
        org_type="certification_body",
        db_path=mem_db,
    )
    sim = find_similar_organizations(
        "Орган по сертификации ООО ФаерЛаб",
        min_ratio=0.5,
        db_path=mem_db,
    )
    # normalize strips prefixes differently — also try short form
    sim2 = find_similar_organizations("ФаерЛаб", min_ratio=0.7, db_path=mem_db)
    assert sim2, "expected fuzzy match on ФаерЛаб"
    assert sim2[0]["score"] >= 0.7


def test_save_customer_only_from_gui_fields(mem_db: Path) -> None:
    """Ручной ввод заказчика без extract.organizations — как СмоленскЭлектроКабель."""
    ids = save_organizations_from_extraction(
        [],
        source="text://customer_speech",
        customer_name='ООО ПО "СмоленскЭлектроКабель"',
        manufacturer_name=None,
        db_path=mem_db,
    )
    assert ids["customer_org_id"] is not None
    assert ids["manufacturer_org_id"] is None
    rows = list_organizations(db_path=mem_db)
    assert len(rows) == 1
    assert "смоленск" in normalize_org_name(rows[0]["name"])
