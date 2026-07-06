"""Тесты YAML-семейств документов."""

from __future__ import annotations

from request_processor.extraction.families.registry import FamilyRegistry


def test_registry_loads_yaml_families() -> None:
    reg = FamilyRegistry.from_directory()
    ids = {f.id for f in reg.families}
    assert "kaluga_periodic_v1" in ids
    assert "speclan_letter_v1" in ids


def test_kaluga_family_detects_periodic_ocr() -> None:
    reg = FamilyRegistry.from_directory()
    family = reg.get("kaluga_periodic_v1")
    assert family is not None
    text = "Nnepuoauyeckie UCNblITAHMA 13x4ok (N,PE) ПВСнг"
    assert family.match_score(text) > 0


def test_speclan_family_detects_letter() -> None:
    reg = FamilyRegistry.from_directory()
    family = reg.get("speclan_letter_v1")
    assert family is not None
    text = "TapaHTuiHoe nucbmMo Mapkax Kabena spetskabel CMELVIAH UTP СПЕЦЛАН"
    assert family.is_confident_match(text)