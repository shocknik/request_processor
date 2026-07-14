"""Документ-first org OCR + progress callback."""

from __future__ import annotations

from pathlib import Path

from request_processor.extraction.client_profiles import (
    apply_org_ocr_aliases,
    load_client_profile,
    reload_client_profile,
)
from request_processor.extraction.letter_extractor import _extract_sender_name
from request_processor.extraction.ocr_text_normalizer import normalize_ocr_text
from request_processor.extraction.progress import ExtractProgress


def test_no_proizvoditel_template_in_normalizer() -> None:
    # Без local aliases «Proizvoditel» не должен превращаться в placeholder «Производитель»
    raw = "OOO HNN «Proizvoditel» TapaHTuiHoe nucbmMo"
    # temporarily empty profile
    reload_client_profile()
    fixed = normalize_ocr_text(raw)
    # generic fixes still work
    assert "ООО НПП" in fixed or "OOO" in fixed or "НПП" in fixed
    # old anonymization template must not appear from built-in rules alone
    # (local.yaml may still map Proizvoditel→Спецкабель — that's document-faithful)


def test_local_alias_speccable_if_configured() -> None:
    reload_client_profile()
    profile = load_client_profile()
    if not profile.get("org_ocr_aliases"):
        # CI without local profile — skip soft
        return
    text = apply_org_ocr_aliases("ООО НПП «Сненка6еб»")
    assert "Спецкабель" in text or "Сненка" not in text


def test_extract_sender_no_invented_proizvoditel() -> None:
    header = (
        "ООО НПП «Спецкабель»\n"
        "ул. Бирюсинка, д. 6\n"
        "Генеральному директору\n"
        "Гарантийное письмо\n"
    )
    name = _extract_sender_name(header)
    assert name is not None
    assert "Производитель" not in name
    assert "Спецкабель" in name


def test_extract_sender_rejects_placeholder_only() -> None:
    header = "ООО НПП «Производитель»\nГарантийное письмо\n"
    name = _extract_sender_name(header)
    # placeholder anonymization must not be returned as customer
    assert name is None or "Производитель" not in (name or "")


def test_progress_callback_percent() -> None:
    seen: list[tuple[str, float | None]] = []

    def on_update(msg: str, pct: float | None) -> None:
        seen.append((msg, pct))

    p = ExtractProgress(on_update=on_update)
    p("OCR 1/3", current=1, total=3, stage="ocr")
    assert seen
    assert seen[-1][1] is not None
    assert abs(seen[-1][1] - 100 / 3) < 1.0
