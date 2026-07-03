"""Модели данных для слоя ИИ-ассистента."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SuggestionSource = Literal["deterministic", "brand_db", "llm", "operator"]


@dataclass
class AssistantContext:
    """Контекст документа для подсказки ассистента."""

    document_text: str | None = None
    ocr_engine: str | None = None
    document_type: str | None = None
    known_brands: set[str] = field(default_factory=set)


@dataclass
class MarkSuggestion:
    """Предложение исправления марки после OCR или ручного ввода."""

    raw: str
    suggested: str
    confidence: float
    source: SuggestionSource
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.raw.strip() != self.suggested.strip()