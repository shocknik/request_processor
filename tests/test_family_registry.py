"""Тесты YAML-семейств документов."""

from __future__ import annotations

from request_processor.extraction.families.registry import FamilyRegistry


def test_registry_loads_yaml_families() -> None:
    reg = FamilyRegistry.from_directory()
    ids = {f.id for f in reg.families}
    assert "periodic_letter_v1" in ids
    assert "lan_letter_v1" in ids


def test_periodic_family_detects_periodic_ocr() -> None:
    reg = FamilyRegistry.from_directory()
    family = reg.get("periodic_letter_v1")
    assert family is not None
    text = "Nnepuoauyeckie UCNblITAHMA 13x4ok (N,PE) ПВСнг"
    assert family.match_score(text) > 0


def test_lan_family_detects_letter() -> None:
    reg = FamilyRegistry.from_directory()
    family = reg.get("lan_letter_v1")
    assert family is not None
    text = "TapaHTuiHoe nucbmMo Mapkax Kabena CMELVIAH UTP СПЕЦЛАН гарантийн"
    assert family.is_confident_match(text)