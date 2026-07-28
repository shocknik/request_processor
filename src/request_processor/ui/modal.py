"""
Модальные Toplevel без «окна 1×1» (D4).

Правильный порядок на Windows/tk:
1. Toplevel + transient + minsize (+ bg)
2. Собрать виджеты (pack/grid)
3. present_modal: update_idletasks → fit geometry → deiconify → grab → focus
4. wait_window (если нужен блокирующий диалог)

Нельзя grab_set / wait_window до geometry — иначе 1×1 «пустое» окно.
StringVar/BooleanVar для полей диалога: ``master=dlg``.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

from .theme import COLORS, fit_window_to_screen


def create_modal(
    parent: tk.Misc,
    *,
    title: str,
    minsize: tuple[int, int] | None = (480, 240),
    bg: str | None = None,
) -> tk.Toplevel:
    """Создать Toplevel для модалки (ещё без grab/geometry)."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    # transient к *withdrawn* parent на Windows → size залипает 1×1
    # (geometry меняет только +x+y). Только если parent уже на экране.
    try:
        if bool(parent.winfo_viewable()):
            dlg.transient(parent)
    except tk.TclError:
        pass
    dlg.configure(bg=bg if bg is not None else COLORS.get("bg", "#F5F7FA"))
    if minsize is not None:
        try:
            dlg.minsize(minsize[0], minsize[1])
        except tk.TclError:
            pass
    # Не grab_set здесь — только после present_modal
    return dlg


def _force_geometry(dlg: tk.Toplevel, prefer_w: int, prefer_h: int) -> None:
    """Явный WxH+centered — единственный надёжный способ уйти с 1×1 на Windows."""
    try:
        sw = max(int(dlg.winfo_screenwidth() or 0), 800)
        sh = max(int(dlg.winfo_screenheight() or 0), 600)
        w, h = max(prefer_w, 200), max(prefer_h, 120)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        try:
            dlg.geometry(f"{prefer_w}x{prefer_h}")
        except tk.TclError:
            pass


def present_modal(
    dlg: tk.Toplevel,
    *,
    prefer_w: int = 560,
    prefer_h: int = 400,
    focus: tk.Misc | None = None,
) -> None:
    """
    Показать модалку после сборки UI.

    Вызывать **после** pack/grid всех виджетов.
    """
    try:
        dlg.update_idletasks()
    except tk.TclError:
        return

    # 1) pin size first (fit_window alone leaves 1x1 when parent withdrawn / pre-map)
    _force_geometry(dlg, prefer_w, prefer_h)

    try:
        fit_window_to_screen(dlg, prefer_w=prefer_w, prefer_h=prefer_h)
    except Exception:
        pass

    # 2) if still tiny after fit — force again
    try:
        geom = dlg.geometry() or ""
        too_small = (
            geom.startswith("1x1")
            or dlg.winfo_width() < 200
            or dlg.winfo_reqwidth() < 50
        )
        if too_small:
            _force_geometry(dlg, prefer_w, prefer_h)
    except tk.TclError:
        _force_geometry(dlg, prefer_w, prefer_h)

    try:
        dlg.deiconify()
        dlg.lift()
    except tk.TclError:
        pass

    # 3) after map some WM reset size — re-pin if needed
    try:
        dlg.update_idletasks()
        geom = dlg.geometry() or ""
        if geom.startswith("1x1") or dlg.winfo_width() < 200:
            _force_geometry(dlg, prefer_w, prefer_h)
    except tk.TclError:
        pass

    try:
        dlg.grab_set()
    except tk.TclError:
        pass

    if focus is not None:
        try:
            focus.focus_set()
        except tk.TclError:
            pass


def run_modal(
    dlg: tk.Toplevel,
    *,
    prefer_w: int = 560,
    prefer_h: int = 400,
    focus: tk.Misc | None = None,
) -> None:
    """present_modal + wait_window (блокирующий диалог)."""
    present_modal(dlg, prefer_w=prefer_w, prefer_h=prefer_h, focus=focus)
    try:
        dlg.wait_window()
    except tk.TclError:
        pass


def modal_var(
    dlg: tk.Toplevel,
    cls: type = tk.StringVar,
    *,
    value: Any = "",
) -> tk.Variable:
    """StringVar/BooleanVar/… с master=dlg (Py 3.12+ / multi-window)."""
    try:
        return cls(master=dlg, value=value)
    except TypeError:
        # BooleanVar etc. may use different signature in edge cases
        var = cls(master=dlg)
        try:
            var.set(value)
        except (tk.TclError, TypeError, ValueError):
            pass
        return var
