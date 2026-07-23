"""Тесты splash-экрана (лёгкий, без полного bootstrap)."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")


def test_splash_shows_progress() -> None:
    from request_processor.ui.widgets.splash import SplashScreen

    try:
        splash = SplashScreen(version="0.9.1-test")
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter: {exc}")
        raise
    try:
        splash.set_progress(25, "Тест этапа", detail="деталь")
        assert splash._progress["value"] == 25
        assert "Тест" in splash._stage_var.get()
        splash.set_progress(100, "Готово")
        assert splash._progress["value"] == 100
    finally:
        splash.close_splash()


def test_gui_module_lazy_export() -> None:
    """gui.py не должен грузить app на import main."""
    import importlib

    import request_processor.ui.gui as gui_mod

    importlib.reload(gui_mod)
    assert callable(gui_mod.main)
    # RequestProcessorApp — ленивый реэкспорт
    App = gui_mod.RequestProcessorApp
    assert App.__name__ == "RequestProcessorApp"
