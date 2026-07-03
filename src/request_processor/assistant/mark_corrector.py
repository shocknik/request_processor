"""
Коррекция марок: детерминированный слой + база брендов.

Задел под LLM (итерация 5.6): сюда подключается провайдер,
который получает контекст документа и список похожих марок из БД.
"""

from __future__ import annotations

from pathlib import Path

from ..config import DB_PATH_DEFAULT
from ..extraction.ocr_mark_normalizer import normalize_mark_after_ocr
from .brand_knowledge import BrandKnowledgeBase
from .models import AssistantContext, MarkSuggestion


class MarkCorrector:
    """Оркестратор исправления марок (без LLM по умолчанию)."""

    def __init__(self, db_path: Path | str = DB_PATH_DEFAULT) -> None:
        self.db_path = Path(db_path)
        self._knowledge = BrandKnowledgeBase(self.db_path)

    def suggest(
        self,
        raw_mark: str,
        *,
        context: AssistantContext | None = None,
    ) -> MarkSuggestion:
        ctx = context or AssistantContext()
        brands = ctx.known_brands or self._knowledge.brands()
        normalized = normalize_mark_after_ocr(raw_mark.strip(), known_brands=brands)

        if normalized == raw_mark.strip():
            return MarkSuggestion(
                raw=raw_mark,
                suggested=normalized,
                confidence=0.95,
                source="deterministic",
                reason="OCR-нормализация без изменений",
            )

        return MarkSuggestion(
            raw=raw_mark,
            suggested=normalized,
            confidence=0.88,
            source="brand_db" if brands else "deterministic",
            reason="Латиница→кириллица и/или snap по cable_marks",
        )

    def reload_knowledge(self) -> None:
        self._knowledge.reload()


_default_corrector: MarkCorrector | None = None


def suggest_mark_correction(
    raw_mark: str,
    *,
    context: AssistantContext | None = None,
    db_path: Path | str = DB_PATH_DEFAULT,
) -> MarkSuggestion:
    """Удобная функция для pdf_extractor и GUI."""
    global _default_corrector
    if _default_corrector is None or Path(db_path) != _default_corrector.db_path:
        _default_corrector = MarkCorrector(db_path)
    return _default_corrector.suggest(raw_mark, context=context)