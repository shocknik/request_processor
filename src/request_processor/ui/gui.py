"""
gui.py — точка входа GUI (обратная совместимость).

Запуск: python -m request_processor.ui.gui
Архитектура: bootstrap (splash) → app.py + shell/ + tabs/ + widgets/

Важно: тяжёлый `app` не импортируется на уровне модуля, чтобы
`start_gui.bat` / ярлык сразу показали splash, а не «тишину» 10–15 с.
"""
from __future__ import annotations

from .bootstrap import run_gui


def main(*, use_splash: bool = True) -> None:
    run_gui(use_splash=use_splash)


# Ленивые реэкспорты для `from request_processor.ui.gui import RequestProcessorApp`
def __getattr__(name: str):
    if name in {
        "RequestProcessorApp",
        "CalcTestEntry",
        "ExtractionDraft",
        "ORG_TYPE_LABELS",
        "ORG_TYPE_VALUES",
    }:
        if name == "RequestProcessorApp":
            from .app import RequestProcessorApp

            return RequestProcessorApp
        from .state import (
            ORG_TYPE_LABELS,
            ORG_TYPE_VALUES,
            CalcTestEntry,
            ExtractionDraft,
        )

        return {
            "CalcTestEntry": CalcTestEntry,
            "ExtractionDraft": ExtractionDraft,
            "ORG_TYPE_LABELS": ORG_TYPE_LABELS,
            "ORG_TYPE_VALUES": ORG_TYPE_VALUES,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
