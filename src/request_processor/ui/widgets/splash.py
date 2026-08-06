"""
Красивый splash-экран Lab_request (только tkinter).

Показывается *до* тяжёлых импортов приложения, чтобы оператор видел
этапы загрузки вместо «тишины» 10–15 с на сетевом диске / cold start.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable


# Локальная палитра (не тянем theme.py — он ходит в logging)
_BG = "#0F172A"          # тёмный slate
_CARD = "#1E293B"
_ACCENT = "#38BDF8"      # sky
_ACCENT_DIM = "#0EA5E9"
_TEXT = "#F8FAFC"
_MUTED = "#94A3B8"
_TRACK = "#334155"
_OK = "#4ADE80"


def _enable_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class SplashScreen(tk.Tk):
    """Отдельное окно-заставка с прогрессом и списком этапов."""

    def __init__(self, *, title: str = "Lab_request", version: str = "") -> None:
        _enable_dpi()
        super().__init__()
        self.title(title)
        self.overrideredirect(True)  # без рамки Windows
        self.configure(bg=_BG)
        self.attributes("-topmost", True)

        # Иконка опциональна: на NAS stat/read может добавить секунды cold start
        try:
            import os

            if os.environ.get("REQUEST_PROCESSOR_SPLASH_ICON", "1") not in ("0", "false"):
                from ...config import PROJECT_ROOT

                ico = PROJECT_ROOT / "assets" / "app_icon.ico"
                # Не ждём сеть: только если путь «быстрый» (локальный диск)
                if ico.is_file() and not str(ico).startswith("\\\\"):
                    self.iconbitmap(default=str(ico))
        except Exception:
            pass

        w, h = 480, 320
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.resizable(False, False)

        outer = tk.Frame(self, bg=_BG, padx=28, pady=24)
        outer.pack(fill="both", expand=True)

        # Бренд
        brand = tk.Frame(outer, bg=_BG)
        brand.pack(fill="x")
        tk.Label(
            brand,
            text="Lab_request",
            font=("Segoe UI Semibold", 22),
            fg=_TEXT,
            bg=_BG,
        ).pack(anchor="w")
        sub = f"Кабельная лаборатория · запуск"
        if version:
            sub = f"v{version} · {sub}"
        tk.Label(
            brand,
            text=sub,
            font=("Segoe UI", 10),
            fg=_MUTED,
            bg=_BG,
        ).pack(anchor="w", pady=(2, 0))

        # Карточка статуса
        card = tk.Frame(outer, bg=_CARD, padx=16, pady=14)
        card.pack(fill="both", expand=True, pady=(18, 12))

        self._stage_var = tk.StringVar(value="Подготовка…")
        tk.Label(
            card,
            textvariable=self._stage_var,
            font=("Segoe UI", 11),
            fg=_TEXT,
            bg=_CARD,
            anchor="w",
            justify="left",
        ).pack(fill="x")

        self._detail_var = tk.StringVar(value="")
        tk.Label(
            card,
            textvariable=self._detail_var,
            font=("Segoe UI", 9),
            fg=_MUTED,
            bg=_CARD,
            anchor="w",
            justify="left",
            wraplength=400,
        ).pack(fill="x", pady=(4, 10))

        # Прогресс-бар (ttk, стилизованный)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Splash.Horizontal.TProgressbar",
            troughcolor=_TRACK,
            background=_ACCENT,
            bordercolor=_CARD,
            lightcolor=_ACCENT,
            darkcolor=_ACCENT_DIM,
            thickness=10,
        )
        self._progress = ttk.Progressbar(
            card,
            style="Splash.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            maximum=100,
            value=0,
            length=400,
        )
        self._progress.pack(fill="x")

        self._pct_var = tk.StringVar(value="0%")
        tk.Label(
            card,
            textvariable=self._pct_var,
            font=("Segoe UI", 9),
            fg=_MUTED,
            bg=_CARD,
            anchor="e",
        ).pack(fill="x", pady=(6, 0))

        # Лента этапов (последние 4)
        self._log_frame = tk.Frame(outer, bg=_BG)
        self._log_frame.pack(fill="x")
        self._log_labels: list[tk.Label] = []
        for _ in range(4):
            lbl = tk.Label(
                self._log_frame,
                text="",
                font=("Consolas", 8),
                fg=_MUTED,
                bg=_BG,
                anchor="w",
            )
            lbl.pack(fill="x")
            self._log_labels.append(lbl)
        self._log_lines: list[str] = []

        self._t0 = time.perf_counter()
        self._closed = False
        self.update_idletasks()
        self.update()

    # ------------------------------------------------------------------ API

    def set_progress(
        self,
        percent: float,
        stage: str,
        *,
        detail: str = "",
        log: bool = True,
    ) -> None:
        """Обновить прогресс (0–100) и текст этапа; сразу перерисовать."""
        if self._closed:
            return
        pct = max(0.0, min(100.0, float(percent)))
        try:
            self._progress["value"] = pct
            self._pct_var.set(f"{pct:.0f}%")
            self._stage_var.set(stage)
            self._detail_var.set(detail or "")
            if log:
                elapsed = time.perf_counter() - self._t0
                line = f"[{elapsed:5.1f}s] {stage}"
                self._log_lines.append(line)
                # показываем хвост
                tail = self._log_lines[-4:]
                for i, lbl in enumerate(self._log_labels):
                    if i < len(tail):
                        lbl.configure(text=tail[i], fg=_OK if i == len(tail) - 1 else _MUTED)
                    else:
                        lbl.configure(text="")
            self.update_idletasks()
            self.update()
        except tk.TclError:
            self._closed = True

    def pump(self) -> None:
        """Прокачать очередь событий (чтобы окно не «замерзало»)."""
        if self._closed:
            return
        try:
            self.update_idletasks()
            self.update()
        except tk.TclError:
            self._closed = True

    def close_splash(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.attributes("-topmost", False)
            self.destroy()
        except tk.TclError:
            pass

    def make_progress_callback(self) -> Callable[[float, str, str], None]:
        """Callback (pct, stage, detail) для ShellMixin / bootstrap."""

        def _cb(pct: float, stage: str, detail: str = "") -> None:
            self.set_progress(pct, stage, detail=detail)

        return _cb


def run_with_splash(build_app: Callable[..., object], *, version: str = "") -> object:
    """
    Показать splash → вызвать build_app(progress=cb) → закрыть splash → вернуть app.

    build_app должен создать и вернуть экземпляр главного окна (tk.Tk).
    """
    splash = SplashScreen(version=version)
    splash.set_progress(3, "Запуск…", detail="Окно загрузки")
    cb = splash.make_progress_callback()
    try:
        app = build_app(progress=cb)
    except Exception:
        splash.close_splash()
        raise
    splash.set_progress(100, "Готово", detail="Открываем Lab_request…")
    splash.pump()
    # Короткая пауза, чтобы «100%» успели увидеть
    try:
        splash.after(180, splash.close_splash)
        splash.update()
        # если app — Tk, не крутим mainloop splash
        splash.close_splash()
    except Exception:
        splash.close_splash()
    return app
