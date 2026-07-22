"""
Глобальная прокрутка колёсиком для Canvas-областей Lab_request.

Проблема tkinter на Windows: MouseWheel доходит только до виджета под
фокусом/курсором; у Canvas со вложенными Frame/Entry/Label колесо
«не работает», пока не кликнуть сам Canvas.

Решение: один bind_all-диспетчер, который находит зарегистрированный
контейнер под курсором и крутит его Canvas. Вложенные Treeview/Text/Listbox
не перехватываем (им оставляем штатный скролл).
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

# Классы, которым отдаём колесо (не крутим родительский Canvas)
_NESTED_SCROLL = frozenset(
    {
        "Treeview",
        "Listbox",
        "Spinbox",
        "TSpinbox",
        "Text",
    }
)


def _widget_is_under(widget: tk.Misc | None, ancestor: tk.Misc) -> bool:
    cur: tk.Misc | None = widget
    while cur is not None:
        if cur == ancestor:
            return True
        cur = getattr(cur, "master", None)
    return False


def _is_nested_scrollable(widget: tk.Misc | None, container: tk.Misc) -> bool:
    """True → не крутить Canvas, пусть крутится Treeview/Text/…"""
    cur: tk.Misc | None = widget
    while cur is not None and cur != container:
        try:
            cls = cur.winfo_class()
        except tk.TclError:
            break
        if cls in _NESTED_SCROLL:
            if cls == "Text":
                # Весь текст на экране — крутим родителя
                try:
                    first, last = cur.yview()  # type: ignore[attr-defined]
                    if float(first) <= 0.001 and float(last) >= 0.999:
                        cur = getattr(cur, "master", None)
                        continue
                except (tk.TclError, TypeError, ValueError, AttributeError):
                    pass
            return True
        cur = getattr(cur, "master", None)
    return False


def _scroll_canvas(canvas: tk.Canvas, event: tk.Event) -> bool:
    """Прокрутить canvas по event. True если сделали scroll."""
    try:
        if not canvas.winfo_exists():
            return False
    except tk.TclError:
        return False

    delta = int(getattr(event, "delta", 0) or 0)
    num = getattr(event, "num", None)
    steps = 0
    if num == 4:  # Linux up
        steps = -1
    elif num == 5:  # Linux down
        steps = 1
    elif delta:
        steps = int(-1 * (delta / 120))
        if steps == 0:
            steps = -1 if delta > 0 else 1
    if steps == 0:
        return False
    try:
        canvas.yview_scroll(steps, "units")
    except tk.TclError:
        return False
    return True


class MousewheelManager:
    """Реестр scrollable Canvas + bind_all на root."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._root: tk.Misc | None = None
        self._bound = False

    def install(self, root: tk.Misc) -> None:
        if self._bound:
            return
        self._root = root
        # add="+" — не затираем чужие bind_all
        root.bind_all("<MouseWheel>", self._on_wheel, add="+")
        root.bind_all("<Button-4>", self._on_wheel, add="+")
        root.bind_all("<Button-5>", self._on_wheel, add="+")
        self._bound = True

    def register(
        self,
        container: tk.Misc,
        canvas: tk.Canvas,
        *,
        priority: int = 0,
    ) -> None:
        """container — область, над которой колесо крутит canvas."""
        # de-dupe same canvas
        self._entries = [e for e in self._entries if e.get("canvas") is not canvas]
        self._entries.append(
            {
                "container": container,
                "canvas": canvas,
                "priority": int(priority),
            }
        )
        self._entries.sort(key=lambda e: e["priority"], reverse=True)
        if not self._bound:
            try:
                self.install(container.winfo_toplevel())
            except tk.TclError:
                pass

    def unregister(self, canvas: tk.Canvas) -> None:
        self._entries = [e for e in self._entries if e.get("canvas") is not canvas]

    def _resolve_widget(self, event: tk.Event) -> tk.Misc | None:
        widget = getattr(event, "widget", None)
        root = self._root
        if root is None:
            return widget if isinstance(widget, tk.Misc) else None
        try:
            x, y = root.winfo_pointerxy()
            under = root.winfo_containing(x, y)
            if under is not None:
                return under
        except tk.TclError:
            pass
        return widget if isinstance(widget, tk.Misc) else None

    def _on_wheel(self, event: tk.Event) -> str | None:
        target = self._resolve_widget(event)
        if target is None:
            return None
        for entry in self._entries:
            container: tk.Misc = entry["container"]
            canvas: tk.Canvas = entry["canvas"]
            try:
                if not container.winfo_ismapped():
                    continue
            except tk.TclError:
                continue
            if not _widget_is_under(target, container):
                continue
            if _is_nested_scrollable(target, container):
                return None
            if _scroll_canvas(canvas, event):
                return "break"
            return None
        return None


_manager = MousewheelManager()


def install_mousewheel(root: tk.Misc) -> None:
    """Вызвать один раз после создания Tk root."""
    _manager.install(root)


def register_canvas_mousewheel(
    container: tk.Misc,
    canvas: tk.Canvas,
    *,
    priority: int = 0,
) -> None:
    """Зарегистрировать Canvas: колесо над container → yview canvas."""
    _manager.register(container, canvas, priority=priority)


def unregister_canvas_mousewheel(canvas: tk.Canvas) -> None:
    _manager.unregister(canvas)
