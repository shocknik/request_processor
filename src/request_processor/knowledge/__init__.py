"""База знаний производителя (марки / испытания / синонимы / пункты ТУ)."""

from .synonyms import load_test_synonyms, resolve_test_phrase

__all__ = ["load_test_synonyms", "resolve_test_phrase"]
