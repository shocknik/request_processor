"""
gui.py — точка входа GUI (обратная совместимость).

Запуск: python -m request_processor.ui.gui
Архитектура: app.py + shell/ + tabs/ + widgets/ + state.py + theme.py
"""
from __future__ import annotations

from .app import RequestProcessorApp, main
from .state import CalcTestEntry, ExtractionDraft, ORG_TYPE_LABELS, ORG_TYPE_VALUES

__all__ = [
    "RequestProcessorApp",
    "main",
    "CalcTestEntry",
    "ExtractionDraft",
    "ORG_TYPE_LABELS",
    "ORG_TYPE_VALUES",
]


if __name__ == "__main__":
    main()
