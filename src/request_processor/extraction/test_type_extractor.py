"""
Определение вида испытаний из текста письма или заявки.

Виды: Приемосдаточные, Периодические, Контрольные, Исследовательские,
Сертификационные, МСИ.
"""

from __future__ import annotations

import re
from typing import Literal

TestTypeKey = Literal[
    "приемосдаточные",
    "периодические",
    "контрольные",
    "исследовательские",
    "сертификационные",
    "мси",
]

TEST_TYPE_LABELS: dict[TestTypeKey, str] = {
    "приемосдаточные": "Приемосдаточные",
    "периодические": "Периодические",
    "контрольные": "Контрольные",
    "исследовательские": "Исследовательские",
    "сертификационные": "Сертификационные",
    "мси": "МСИ",
}

TEST_TYPE_OPTIONS: tuple[str, ...] = tuple(TEST_TYPE_LABELS.values())

_GENITIVE_LABELS: dict[TestTypeKey, str] = {
    "приемосдаточные": "приемосдаточных",
    "периодические": "периодических",
    "контрольные": "контрольных",
    "исследовательские": "исследовательских",
    "сертификационные": "сертификационных",
    "мси": "МСИ",
}

_DEFAULT_KEY: TestTypeKey = "периодические"

_PATTERNS: tuple[tuple[TestTypeKey, tuple[str, ...]], ...] = (
    ("мси", ("мси", "межлаборатор", "сравнительн")),
    ("сертификационные", ("сертификац",)),
    ("приемосдаточные", ("приемо-сдаточ", "приёмо-сдаточ", "приемосдаточ", "приёмосдаточ", "пс испытан")),
    ("контрольные", ("контрольн",)),
    ("исследовательские", ("исследовательск",)),
    ("периодические", ("периодич",)),
)


def detect_test_type(text: str | None) -> TestTypeKey:
    """Определяет вид испытаний по тексту первичного документа."""
    if not text or not text.strip():
        return _DEFAULT_KEY
    normalized = re.sub(r"\s+", " ", text.lower())

    for key, phrases in _PATTERNS:
        if any(phrase in normalized for phrase in phrases):
            return key
    return _DEFAULT_KEY


def format_test_type_label(key: str | None) -> str:
    """Человекочитаемая подпись для GUI и КП."""
    if not key:
        return TEST_TYPE_LABELS[_DEFAULT_KEY]
    low = key.strip().lower()
    if low in TEST_TYPE_LABELS:
        return TEST_TYPE_LABELS[low]  # type: ignore[index]
    for k, label in TEST_TYPE_LABELS.items():
        if label.lower() == low:
            return label
    return key.strip() or TEST_TYPE_LABELS[_DEFAULT_KEY]


def label_to_key(label: str | None) -> TestTypeKey:
    """Преобразует подпись из GUI в ключ."""
    if not label:
        return _DEFAULT_KEY
    low = label.strip().lower()
    for key, name in TEST_TYPE_LABELS.items():
        if name.lower() == low:
            return key
    return detect_test_type(label)


def build_kp_subject(text: str | None = None, *, test_type: str | None = None) -> str:
    """Фраза для вводной КП: «Проведение … испытаний»."""
    key = label_to_key(test_type) if test_type else detect_test_type(text)
    genitive = _GENITIVE_LABELS.get(key, TEST_TYPE_LABELS[key].lower())
    return f"Проведение {genitive} испытаний"