"""
Коррекция марок: детерминированный слой + fuzzy snap по cable_marks.

Задел под LLM (итерация 5.6): сюда подключается провайдер,
который получает контекст документа и список похожих марок из БД.
"""

from __future__ import annotations

from pathlib import Path

from ..config import DB_PATH_DEFAULT
from ..extraction.ocr_mark_normalizer import normalize_mark_after_ocr
from ..persistence.sqlite_repo import get_assistant_llm_settings
from .brand_knowledge import BrandKnowledgeBase
from .fuzzy_match import best_mark_matches, fuzzy_snap_mark
from .llm_provider import should_try_llm, try_llm_suggestion
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
        raw = (raw_mark or "").strip()
        if not raw:
            return MarkSuggestion(
                raw=raw_mark or "",
                suggested=raw_mark or "",
                confidence=0.0,
                source="deterministic",
                reason="Пустая марка",
            )

        brands = ctx.known_brands or self._knowledge.brands()
        normalized = normalize_mark_after_ocr(raw, known_brands=brands)

        # 1) Правила OCR (латиница → кириллица, fire-class, snap префикса)
        if normalized != raw:
            # 2) Поверх нормализации — fuzzy к полной марке из БД
            snap, score = self._try_fuzzy(normalized, ctx)
            if snap and snap != normalized:
                snap_result = MarkSuggestion(
                    raw=raw_mark,
                    suggested=snap,
                    confidence=min(0.93, 0.75 + score * 0.2),
                    source="brand_db",
                    reason=f"OCR-нормализация + fuzzy snap ({score:.0%})",
                )
                return self._maybe_llm(raw_mark, snap_result, ctx)
            norm_result = MarkSuggestion(
                raw=raw_mark,
                suggested=normalized,
                confidence=0.88,
                source="brand_db" if brands else "deterministic",
                reason="Латиница→кириллица и/или snap по cable_marks",
            )
            return self._maybe_llm(raw_mark, norm_result, ctx)

        # 3) Без изменений от normalizer — всё равно пробуем fuzzy (OCR-мусор «почти марка»)
        snap, score = self._try_fuzzy(raw, ctx)
        if snap and snap != raw:
            fuzzy_result = MarkSuggestion(
                raw=raw_mark,
                suggested=snap,
                confidence=min(0.92, 0.70 + score * 0.25),
                source="brand_db",
                reason=f"Fuzzy snap к cable_marks ({score:.0%})",
            )
            return self._maybe_llm(raw_mark, fuzzy_result, ctx)

        det = MarkSuggestion(
            raw=raw_mark,
            suggested=normalized,
            confidence=0.95,
            source="deterministic",
            reason="OCR-нормализация без изменений",
        )
        return self._maybe_llm(raw_mark, det, ctx)

    def _maybe_llm(
        self,
        raw_mark: str,
        det: MarkSuggestion,
        ctx: AssistantContext,
    ) -> MarkSuggestion:
        """Опциональный LLM поверх детерминированного результата."""
        settings = get_assistant_llm_settings(self.db_path)
        if not should_try_llm(det, settings):
            return det
        candidates = [name for name, _ in self.candidates(raw_mark, limit=5, context=ctx)]
        llm = try_llm_suggestion(
            raw_mark,
            context=ctx,
            candidates=candidates,
            settings=settings,
        )
        if llm is None:
            return det
        if llm.changed and llm.confidence >= det.confidence - 0.05:
            return llm
        if not det.changed and llm.changed:
            return llm
        return det

    def suggest_many(
        self,
        marks: list[str],
        *,
        context: AssistantContext | None = None,
        only_changed: bool = True,
    ) -> list[MarkSuggestion]:
        """Пакет подсказок (для GUI-диалога)."""
        out: list[MarkSuggestion] = []
        for m in marks:
            s = self.suggest(m, context=context)
            if only_changed and not s.changed:
                continue
            out.append(s)
        return out

    def candidates(
        self,
        raw_mark: str,
        *,
        limit: int = 5,
        context: AssistantContext | None = None,
    ) -> list[tuple[str, float]]:
        """Альтернативы для панели оператора."""
        ctx = context or AssistantContext()
        pool = self._candidate_pool(ctx)
        normalized = normalize_mark_after_ocr(
            raw_mark.strip(),
            known_brands=ctx.known_brands or self._knowledge.brands(),
        )
        return best_mark_matches(normalized or raw_mark, pool, limit=limit)

    def _try_fuzzy(
        self,
        mark: str,
        ctx: AssistantContext,
    ) -> tuple[str | None, float]:
        pool = self._candidate_pool(ctx)
        if not pool:
            return None, 0.0
        return fuzzy_snap_mark(mark, pool, min_score=0.86)

    def _candidate_pool(self, ctx: AssistantContext) -> set[str]:
        pool = set(self._knowledge.full_marks(limit=800))
        # бренды как слабые кандидаты не даём — только полные марки
        if ctx.document_text:
            # лёгкий буст: ничего не фильтруем по тексту пока (задел)
            pass
        return pool

    def reload_knowledge(self) -> None:
        self._knowledge.reload()


_default_corrector: MarkCorrector | None = None


def get_mark_corrector(db_path: Path | str = DB_PATH_DEFAULT) -> MarkCorrector:
    global _default_corrector
    if _default_corrector is None or Path(db_path) != _default_corrector.db_path:
        _default_corrector = MarkCorrector(db_path)
    return _default_corrector


def suggest_mark_correction(
    raw_mark: str,
    *,
    context: AssistantContext | None = None,
    db_path: Path | str = DB_PATH_DEFAULT,
) -> MarkSuggestion:
    """Удобная функция для pdf_extractor и GUI."""
    return get_mark_corrector(db_path).suggest(raw_mark, context=context)
