"""ИИ-ассистент: подсказки по маркам и документам (v0.9+)."""

from .feedback import AssistantFeedbackEvent, append_assistant_feedback
from .llm_provider import check_ollama_health, default_llm_settings
from .mark_corrector import MarkCorrector, get_mark_corrector, suggest_mark_correction
from .models import AssistantContext, MarkSuggestion

__all__ = [
    "AssistantContext",
    "AssistantFeedbackEvent",
    "MarkCorrector",
    "MarkSuggestion",
    "append_assistant_feedback",
    "check_ollama_health",
    "default_llm_settings",
    "get_mark_corrector",
    "suggest_mark_correction",
]