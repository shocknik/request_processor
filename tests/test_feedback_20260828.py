"""Регрессии волн A–B — обратная связь work 28.08.2026.

A: UNIQUE confirm, логин Windows, честный текст ошибки.
B: дедуп СПЕЦЛАН, склейка оптики СП-|ОКС, копирование/нумерация марок.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from request_processor.extraction.organization_extractor import (
    is_placeholder_org_name,
    normalize_org_name,
)
from request_processor.models import OrganizationExtract
from request_processor.persistence.sqlite_repo import (
    attach_organization_details,
    create_organization,
    get_organization_by_id,
    init_db,
    list_organizations,
    merge_organizations,
    save_document_extraction,
    update_organization,
    upsert_organization,
)
from request_processor.extraction.ocr_mark_normalizer import normalize_mark_after_ocr
from request_processor.extraction.pdf_extractor import find_cable_marks
from request_processor.ui.state import RequestPageState
from request_processor.ui.tabs.pdf_tab import request_primary_error_text


@pytest.fixture()
def mem_db(tmp_path: Path) -> Path:
    db = tmp_path / "wave_a.db"
    init_db(db)
    return db


def test_placeholder_login_and_labels() -> None:
    assert is_placeholder_org_name("n.molchanov")
    assert is_placeholder_org_name("N.Molchanov")
    assert is_placeholder_org_name("заказчик")
    assert is_placeholder_org_name("Производитель")
    assert is_placeholder_org_name("")
    assert not is_placeholder_org_name('ООО НПП «Спецкабель»')
    assert not is_placeholder_org_name("Кабельный завод Полимет")
    assert not is_placeholder_org_name("SUPR")


def test_speckabel_names_normalize_equal() -> None:
    a = normalize_org_name("ООО НПП «Спецкабель»")
    b = normalize_org_name("ООО «НПП СПЕЦКАБЕЛЬ»")
    assert a == b == "нпп спецкабель"


def _two_speckabel(mem_db: Path) -> tuple[int, int]:
    """Как на work: id с ИНН и дубль без ИНН, один name_normalized."""
    with_inn = create_organization(
        name="ООО НПП «Спецкабель»",
        inn="7701165130",
        db_path=mem_db,
    )
    empty = create_organization(
        name="ООО «НПП СПЕЦКАБЕЛЬ»",
        db_path=mem_db,
    )
    assert with_inn != empty
    return with_inn, empty


def test_attach_inn_merges_duplicate_speckabel(mem_db: Path) -> None:
    """A1/A2: дописать ИНН дублю не падает UNIQUE — сливаем в карточку с ИНН."""
    keep, drop = _two_speckabel(mem_db)
    extraction_id = save_document_extraction(
        source_path="letter.pdf",
        source_type="pdf",
        text="x",
        marks_count=2,
        customer_org_id=drop,
        db_path=mem_db,
    )
    surviving = attach_organization_details(
        drop,
        inn="7701165130",
        address="Москва, ул. Бирюсинка",
        db_path=mem_db,
    )
    assert surviving == keep
    assert get_organization_by_id(drop, mem_db) is None
    row = get_organization_by_id(keep, mem_db)
    assert row is not None
    assert row["inn"] == "7701165130"
    rows = list_organizations(search="спецкабель", db_path=mem_db)
    assert len(rows) == 1
    assert rows[0]["id"] == keep

    import sqlite3

    con = sqlite3.connect(mem_db)
    con.row_factory = sqlite3.Row
    ext = con.execute(
        "SELECT customer_org_id FROM document_extractions WHERE id = ?",
        (extraction_id,),
    ).fetchone()
    con.close()
    assert ext["customer_org_id"] == keep


def test_update_organization_unique_merges(mem_db: Path) -> None:
    keep, drop = _two_speckabel(mem_db)
    ok = update_organization(
        drop,
        name="ООО «НПП СПЕЦКАБЕЛЬ»",
        inn="7701165130",
        db_path=mem_db,
    )
    assert ok is True
    assert get_organization_by_id(drop, mem_db) is None
    assert get_organization_by_id(keep, mem_db) is not None


def test_upsert_with_inn_merges_empty_duplicate(mem_db: Path) -> None:
    keep, drop = _two_speckabel(mem_db)
    got = upsert_organization(
        OrganizationExtract(
            name="ООО «НПП СПЕЦКАБЕЛЬ»",
            inn="7701165130",
            address="Бирюсинка",
            org_type="manufacturer",
            role="manufacturer",
            confidence=0.9,
        ),
        source="test",
        db_path=mem_db,
    )
    assert got == keep
    assert get_organization_by_id(drop, mem_db) is None


def test_merge_retargets_extraction_fk(mem_db: Path) -> None:
    keep, drop = _two_speckabel(mem_db)
    save_document_extraction(
        source_path="a.pdf",
        source_type="pdf",
        text="t",
        marks_count=1,
        manufacturer_org_id=drop,
        db_path=mem_db,
    )
    merge_organizations(keep, drop, db_path=mem_db)
    import sqlite3

    con = sqlite3.connect(mem_db)
    n = con.execute(
        "SELECT COUNT(*) FROM document_extractions WHERE manufacturer_org_id = ?",
        (keep,),
    ).fetchone()[0]
    leftover = con.execute(
        "SELECT COUNT(*) FROM organizations WHERE id = ?", (drop,)
    ).fetchone()[0]
    con.close()
    assert n == 1
    assert leftover == 0


def test_list_organizations_hides_login(mem_db: Path) -> None:
    import sqlite3
    from datetime import datetime

    create_organization(name='ООО НПП «Спецкабель»', db_path=mem_db)
    now = datetime.now().isoformat()
    con = sqlite3.connect(mem_db)
    con.execute(
        """
        INSERT INTO organizations (name, name_normalized, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        ("n.molchanov", "n.molchanov", now, now),
    )
    con.commit()
    con.close()
    all_rows = list_organizations(db_path=mem_db)
    hidden = list_organizations(db_path=mem_db, exclude_placeholders=True)
    names_all = {r["name"] for r in all_rows}
    names_hid = {r["name"] for r in hidden}
    assert "n.molchanov" in names_all
    assert "n.molchanov" not in names_hid
    assert any("Спецкабель" in n or "СПЕЦКАБЕЛЬ" in n for n in names_hid)


def test_create_login_org_rejected(mem_db: Path) -> None:
    with pytest.raises(ValueError, match="логин"):
        create_organization(name="n.molchanov", db_path=mem_db)


def test_upsert_placeholder_does_not_insert(mem_db: Path) -> None:
    oid = upsert_organization(
        OrganizationExtract(name="n.molchanov", confidence=0.4),
        db_path=mem_db,
    )
    assert oid == 0
    assert list_organizations(db_path=mem_db) == []


def test_confirm_error_text_not_extract() -> None:
    exc = Exception("UNIQUE constraint failed: index 'idx_organizations_dedup'")
    msg = request_primary_error_text(RequestPageState.REVIEW_REQUIRED, exc)
    assert "организац" in msg.lower()
    assert "извлечение" not in msg.lower() or "не запускайте разбор" in msg.lower()
    assert "UNIQUE" in msg
    extract_msg = request_primary_error_text(RequestPageState.FILE_SELECTED, exc)
    assert extract_msg.startswith("Не удалось запустить извлечение")


_SPECLAN_LETTER_1610 = """
Гарантийное письмо
Просим Вас провести приемо-сдаточные испытания на следующих
марках кабеля:
1. СПЕЦЛАН F/UTP cat 5e ZH нг(А)-HF 2x2x0,52 ТУ 16.К99-058-2014 в
количестве 272m, 100m (проверочная бухта);
2. СПЕЦЛАН F/UTP cat 5e ZH нг(А)-HF 4x2x0,52 ТУ 16.К99-058-2014 в
количестве 210m, 100m (проверочная бухта);
3. СПЕЦЛАН F/UTP cat 5e ZH нг(А)-НЕ 2x2x0,52 ТУ 16.К99-058-2014 в
количестве 100M;
4. СПЕЦЛАН F/UTP cat 5e ZH нг(А)-HF 4x2x0,52 ТУ 16.К99-058-2014 в
количестве 1995m, 100m (проверочная бухта);
5. СПЕЦЛАН F/UTP Cat Se ZH нг(А)-НЕ 4x2x0,52 ТУ 16.К99-058-2014 в
количестве 180m, 100m (проверочная бухта);
6. СПЕЦЛАН F/UTP cat 5e ZH нг(А)-HF 2x2x0,52 ТУ 16.К99-058-2014 в
количестве 4100m, 100m (проверочная бухта);
7. СПЕЦЛАН F/UTP cat 5e ZH нг(А)-НF 4x2x0.52 ТУ 16.К99-058-2014 в
количестве 100m.
Последующую оплату гарантируем.
"""


def test_speclan_letter_dedupes_to_two_sizes() -> None:
    """B3: семь пунктов письма №1610 → две конструкции (2x2 и 4x2)."""
    marks = find_cable_marks(_SPECLAN_LETTER_1610)
    joined = " | ".join(m.mark for m in marks)
    assert len(marks) == 2, joined
    keys = [
        re.sub(r"\s+", "", m.mark.lower()).replace("x", "х").replace(",", ".")
        for m in marks
    ]
    assert any("2х2" in k for k in keys), joined
    assert any("4х2" in k for k in keys), joined
    for m in marks:
        assert "HF" in m.mark.upper(), m.mark
        compact = m.mark.upper().replace(" ", "")
        assert "5E" in compact, m.mark
        assert "-НЕ" not in compact, m.mark


def test_optical_wrap_sp_ok_ekne() -> None:
    """B4: направление 19.08 — СП-| + ОКСнг(А)-ЕКНЕ через перенос."""
    text = (
        "Кабель оптический огнестойкий, марки СП-| метр 06.2026 "
        "ГОСТ 31565-2012 п.5.8 | ГОСТ IEC 6033 1-25\n"
        "ОКСнг(А)-ЕКНЕ-М8П-4А-1,5,\n"
        "изготавливаемого по ТУ 3587-017-70464675-2015\n"
    )
    marks = find_cable_marks(text)
    joined = " | ".join(m.mark for m in marks)
    assert marks, joined
    assert any("СП-ОКС" in m.mark.upper() for m in marks), joined
    assert any("FRHF" in m.mark.upper() for m in marks), joined
    assert not any("ЕКНЕ" in m.mark.upper() for m in marks), joined


def test_optical_wrap_frnf_m8ii() -> None:
    text = (
        "марки СП-| метр 06.2026 ГОСТ 31565-2012 п.5.8 | ГОСТ IEC 6033 1-25\n"
        "ОКСнг(А)-FRНF-М8II-4А-1,5,\n"
    )
    marks = find_cable_marks(text)
    joined = " | ".join(m.mark for m in marks)
    assert any("СП-ОКС" in m.mark.upper() for m in marks), joined
    assert any("FRHF" in m.mark.upper() for m in marks), joined
    assert any("М8П" in m.mark.upper() or "M8P" in m.mark.upper() for m in marks), joined


def test_marks_tree_has_number_and_copy() -> None:
    """B1/B2: колонка № и копирование в исходнике вкладки Заявка."""
    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "request_processor"
        / "ui"
        / "tabs"
        / "pdf_tab.py"
    )
    text = src.read_text(encoding="utf-8")
    assert '("num", "№"' in text or '("num", "№",' in text
    assert "_copy_selected_draft_mark" in text
    assert 'text="Копировать"' in text

