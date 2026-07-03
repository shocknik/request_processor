"""ИИ-ассистент: подсказки по маркам и документам (задел v0.8.2+)."""

from .mark_corrector import MarkCorrector, suggest_mark_correction
from .models import MarkSuggestion, AssistantContext

__all__ = [
    "AssistantContext",
    "MarkCorrector",
    "MarkSuggestion",
    "suggest_mark_correction",
]