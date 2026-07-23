"""
Лёгкий bootstrap GUI: splash → импорты → init → mainloop.

Важно: этот модуль должен импортировать минимум (tkinter + splash),
чтобы окно загрузки появилось *до* тяжёлого `ui.app` / pdf / openpyxl.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def run_gui(
    *,
    use_splash: bool = True,
    db_path: Path | None = None,
) -> None:
    """Запуск Lab_request с опциональным splash-экраном."""
    t0 = time.perf_counter()

    if not use_splash:
        from ..logging_setup import setup_logging
        from .app import RequestProcessorApp
        from .theme import enable_windows_dpi_awareness

        enable_windows_dpi_awareness()
        setup_logging(level="INFO")
        kwargs: dict[str, Any] = {}
        if db_path is not None:
            kwargs["db_path"] = db_path
        app = RequestProcessorApp(**kwargs)
        app.mainloop()
        return

    from .widgets.splash import SplashScreen

    version = ""
    try:
        from request_processor import __version__

        version = __version__
    except Exception:
        pass

    splash = SplashScreen(version=version)
    splash.set_progress(5, "Запуск Lab_request…", detail="Инициализация загрузчика")
    progress = splash.make_progress_callback()

    def _step(pct: float, stage: str, detail: str = "") -> None:
        progress(pct, stage, detail)

    try:
        _step(8, "Служебные модули…", "логирование, DPI")
        from ..logging_setup import get_logger, setup_logging
        from .theme import enable_windows_dpi_awareness

        enable_windows_dpi_awareness()
        setup_logging(level="INFO")
        log = get_logger("ui.gui")
        log.info("bootstrap: splash shown", extra={"tag": "Старт"})

        _step(12, "Загрузка ядра…", "модели, БД-слой, расчёт, GUI-модули")
        t_imp = time.perf_counter()
        from .app import RequestProcessorApp  # тяжёлый импорт

        imp_ms = (time.perf_counter() - t_imp) * 1000
        log.info("bootstrap: import app %.0f ms", imp_ms, extra={"tag": "Старт"})
        _step(50, "Модули загружены", detail=f"{imp_ms:.0f} ms")

        _step(52, "Создание главного окна…", "пока скрыто за splash")
        kwargs = {"progress": progress, "start_hidden": True}
        if db_path is not None:
            kwargs["db_path"] = db_path
        app = RequestProcessorApp(**kwargs)

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "bootstrap: ready total=%.0f ms → mainloop",
            total_ms,
            extra={"tag": "Старт"},
        )
        _step(100, "Готово", detail=f"старт за {total_ms:.0f} ms")
        splash.pump()

        # Закрыть splash и показать главное окно
        splash.close_splash()
        try:
            app.deiconify()
            app.lift()
            app.focus_force()
        except Exception:
            pass
        app.mainloop()
    except Exception:
        try:
            splash.close_splash()
        except Exception:
            pass
        raise


def make_app_for_tests(
    db_path: Path,
    *,
    progress: Callable[[float, str, str], None] | None = None,
) -> Any:
    """Фабрика для pytest (без splash, окно можно withdraw снаружи)."""
    from .app import RequestProcessorApp

    return RequestProcessorApp(db_path=db_path, progress=progress, start_hidden=False)
