"""Регрессии по обратной связи work 06.08.2026 (org search, document, marks OCR)."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.extraction.ocr_mark_normalizer import (
    normalize_lan_homoglyphs,
    normalize_mark_after_ocr,
)
from request_processor.extraction.pdf_extractor import extract_from_text, find_cable_marks
from request_processor.parsing.cable_mark_parser import extract_document_from_text
from request_processor.persistence.sqlite_repo import (
    create_organization,
    init_db,
    list_organizations,
)


@pytest.fixture()
def mem_db(tmp_path: Path) -> Path:
    db = tmp_path / "orgs.db"
    init_db(db)
    create_organization(
        name='ООО "Тольяттинский кабельный завод"',
        inn="632147331",
        address="г. Тольятти, ул. Северная",
        db_path=db,
    )
    create_organization(
        name="ООО НПП «Спецкабель»",
        inn="7701165130",
        address="Москва, Бирюсинка",
        db_path=db,
    )
    return db


def test_org_search_casefold_cyrillic(mem_db: Path) -> None:
    assert len(list_organizations(search="Тольят", db_path=mem_db)) == 1
    assert len(list_organizations(search="тольят", db_path=mem_db)) == 1
    assert len(list_organizations(search="ТОЛЬЯТ", db_path=mem_db)) == 1
    assert len(list_organizations(search="СПЕЦ", db_path=mem_db)) == 1
    assert len(list_organizations(search="спец", db_path=mem_db)) == 1
    assert len(list_organizations(search="кабель", db_path=mem_db)) >= 1
    # multi-token
    assert len(list_organizations(search="тольят завод", db_path=mem_db)) == 1


def test_document_not_stoimostyu() -> None:
    letter = (
        "Во вложении программа. Просим дать коммерческое предложение "
        "со стоимостью услуг и сроками. U/UTP cat 5e 2x2x0.52 PE"
    )
    assert extract_document_from_text(letter) is None
    assert extract_document_from_text("стоимостью") is None
    assert extract_document_from_text("СТО 12345-2020") is not None
    assert extract_document_from_text("ТУ 16.К99-037-2009") is not None


def test_lan_homoglyphs_utp_pvc() -> None:
    raw = "SF/UТР Cat 6 РVС нг(А)-LS 4х2х0,57-145"
    fixed = normalize_lan_homoglyphs(raw)
    assert "UTP" in fixed.upper() or "U/UTP" in fixed.upper() or "SF/UTP" in fixed
    assert "PVC" in fixed.upper()
    assert "UТР" not in fixed
    assert "РVС" not in fixed
    mark = normalize_mark_after_ocr(raw)
    assert "ТР" not in mark or "UTP" in mark.upper()


def test_fire_ocr_evne_to_frhf() -> None:
    raw = "КСБКНГ(А)-ЕВНЕ 4х2x0,80"
    fixed = normalize_mark_after_ocr(raw)
    assert "FRHF" in fixed.upper()
    assert "ЕВНЕ" not in fixed.upper()


def test_find_ksbpp_and_ksspp() -> None:
    text = (
        "Кабель КСВПП-5е 2х2х0.52 ТУ ФКС-002-2016. "
        "Марки нашего производства: КССПП 5е 2х2х0,52 и КССПП 5е 4х2х0,52"
    )
    marks = find_cable_marks(text)
    joined = " | ".join(m.mark for m in marks)
    assert any("КСВПП" in m.mark for m in marks), joined
    assert any("КССПП" in m.mark for m in marks), joined


def test_find_generic_lan_with_sheath_before_size() -> None:
    text = (
        "Образцы: SF/UTP Cat 6 PVC нг(А)-LS 4х2х0,57-145; "
        "S/FTP Cat 6A PVC нг(А)-LS 4х2х0,57-145. ГОСТ Р 54429-2011"
    )
    marks = find_cable_marks(text)
    joined = " | ".join(m.mark for m in marks)
    assert any("SF/UTP" in m.mark.upper() or "SF/" in m.mark.upper() for m in marks), joined
    assert any("S/FTP" in m.mark.upper() or "FTP" in m.mark.upper() for m in marks), joined


def test_free_text_work_letter_no_stoimost_doc() -> None:
    letter = (
        "Во вложении программа и методика испытаний кабелей связи. "
        "Просим дать коммерческое предложение со стоимостью услуг и сроками, спасибо.\n"
        "по два образца кабель витая пара - U/UTP cat 5e 2x2x0.52 PE – 2 шт,"
        "U/UTP cat 5e 4x2x0.52 PE – 2 шт.:\n"
        "Марки нашего производства: КССПП 5е 2х2х0,52 и КССПП 5е 4х2х0,52"
    )
    result = extract_from_text(letter, source_label="customer_speech")
    assert len(result.cable_marks) >= 2
    for m in result.cable_marks:
        doc = (m.document or "").lower()
        assert "стоимост" not in doc, m
    # U/UTP и/или КССПП
    blob = " ".join(m.mark for m in result.cable_marks)
    assert "UTP" in blob.upper() or "КССПП" in blob


def test_ocr_garbage_ksbk_letter_list() -> None:
    text = (
        "Просим провести приемо-сдаточные испытания на следующих марках кабеля:\n"
        "1. КСБКНГ(А)-ЕВНЕ 4x2x0,80 ТУ 16.К99-037-2009 в количестве 100m."
    )
    marks = find_cable_marks(text)
    assert marks, "должна найтись хотя бы одна марка"
    fixed = [normalize_mark_after_ocr(m.mark) for m in marks]
    assert any("КСБК" in f.upper() for f in fixed)
    assert any("FRHF" in f.upper() for f in fixed)
