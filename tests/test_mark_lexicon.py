"""Словарь марок из справочника 300 — загрузка и поиск в тексте."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.extraction.mark_lexicon import (
    find_lexicon_marks_in_text,
    load_mark_lexicon,
    lookup_brand,
)
from request_processor.extraction.pdf_extractor import extract_from_text


@pytest.fixture(autouse=True)
def _reload_lexicon() -> None:
    load_mark_lexicon.cache_clear()
    yield
    load_mark_lexicon.cache_clear()


def test_lexicon_file_loads() -> None:
    lex = load_mark_lexicon()
    assert lex["brands"], "ожидается встроенный mark_lexicon_v1.yaml"
    assert len(lex["brands"]) >= 50
    assert lookup_brand("ВВГ") is not None or lookup_brand("ВВГнг(А)-LS") is not None


def test_lookup_does_not_upgrade_kg_to_kg_hl() -> None:
    """«КГ» в тексте не должно превращаться в «КГ-ХЛ»."""
    load_mark_lexicon.cache_clear()
    got = lookup_brand("КГ")
    if got is None:
        pytest.skip("КГ нет в словаре")
    assert got == "КГ" or not got.upper().startswith("КГ-")


def test_find_vvg_in_sentence() -> None:
    text = "Нужен кабель ВВГнг(А)-LS для периодических испытаний, сечение уточним."
    hits = find_lexicon_marks_in_text(text)
    names = " ".join(h[0] for h in hits)
    assert "ВВГ" in names


def test_extract_from_text_uses_lexicon() -> None:
    text = "Просим стоимость на кабель КВВГнг(А)-LS, без указания сечения."
    result = extract_from_text(text, source_label="customer_speech")
    marks = " ".join(m.mark for m in result.cable_marks)
    assert "КВВГ" in marks


def test_extract_still_finds_kage_without_lexicon() -> None:
    """Старое поведение speech: «кабель КАГЭ» (нет в справочнике 300)."""
    text = "У нас в работе кабель КАГЭ с поставкой на АЭС."
    result = extract_from_text(text)
    assert any("КАГЭ" in m.mark for m in result.cable_marks)


def test_three_fragments_on_separate_lines() -> None:
    """Переписка: три куска марки на отдельных строках — все три."""
    text = """Никита, проверь, пожалуйста
ВВГ
Еще нужна климатика
U/UTP
Заказчик просил то се
КВПФэМ"""
    result = extract_from_text(text, source_label="customer_speech")
    marks = " ".join(m.mark for m in result.cable_marks)
    assert "ВВГ" in marks
    assert "U/UTP" in marks.upper().replace("У", "U") or "UTP" in marks.upper()
    assert any(
        "КВП" in m.mark.upper().replace("Ё", "Е") for m in result.cable_marks
    ), marks


def test_packaged_yaml_exists() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "request_processor"
        / "extraction"
        / "resources"
        / "mark_lexicon_v1.yaml"
    )
    assert path.is_file(), path
