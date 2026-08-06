"""
Лёгкий bootstrap GUI: splash → импорты → init → mainloop.

Важно: этот модуль должен импортировать минимум (tkinter + splash),
чтобы окно загрузки появилось *до* тяжёлого `ui.app` / pdf / openpyxl.

На work (NAS) cold start 10–20 с часто *до* Python-кода (pythonw с W:\\).
Здесь считаем этапы после входа в run_gui и сразу рисуем splash.
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

    # 1) Splash как можно раньше — без version/logging/icon с NAS
    from .widgets.splash import SplashScreen

    t_before_splash = time.perf_counter()
    splash = SplashScreen(version="")  # version подставим после лёгкого import
    splash.set_progress(3, "Запуск Lab_request…", detail="Окно загрузки")
    try:
        splash.update_idletasks()
        splash.update()
    except Exception:
        pass
    t_splash = time.perf_counter()
    progress = splash.make_progress_callback()

    def _step(pct: float, stage: str, detail: str = "") -> None:
        progress(pct, stage, detail)
        try:
            splash.pump()
        except Exception:
            pass

    try:
        _step(6, "Служебные модули…", "версия, логирование, DPI")
        version = ""
        try:
            from request_processor import __version__

            version = __version__
            if version:
                try:
                    splash._stage_var.set(f"v{version} · Запуск…")
                except Exception:
                    pass
        except Exception:
            pass

        from ..logging_setup import get_logger, setup_logging
        from .theme import enable_windows_dpi_awareness

        enable_windows_dpi_awareness()
        # Логи на NAS могут быть медленными — не блокируем UI дольше необходимого
        setup_logging(level="INFO")
        log = get_logger("ui.gui")
        pre_ms = (t_splash - t0) * 1000
        log.info(
            "bootstrap: splash shown t_pre_splash=%.0f ms (create=%.0f ms)",
            pre_ms,
            (t_splash - t_before_splash) * 1000,
            extra={"tag": "Старт"},
        )

        _step(12, "Загрузка ядра…", "модели, БД-слой, расчёт, GUI-модули")
        t_imp = time.perf_counter()
        from .app import RequestProcessorApp  # тяжёлый импорт

        imp_ms = (time.perf_counter() - t_imp) * 1000
        log.info(
            "bootstrap: import app %.0f ms t_import=%.0f",
            imp_ms,
            imp_ms,
            extra={"tag": "Старт"},
        )
        _step(50, "Модули загружены", detail=f"{imp_ms:.0f} ms")

        _step(52, "Создание главного окна…", "пока скрыто за splash")
        kwargs: dict[str, Any] = {"progress": progress, "start_hidden": True}
        if db_path is not None:
            kwargs["db_path"] = db_path
        app = RequestProcessorApp(**kwargs)

        total_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "bootstrap: ready total=%.0f ms t_pre_splash=%.0f t_import=%.0f → mainloop",
            total_ms,
            pre_ms,
            imp_ms,
            extra={"tag": "Старт"},
        )
        _step(100, "Готово", detail=f"старт за {total_ms:.0f} ms")
        splash.pump()

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
