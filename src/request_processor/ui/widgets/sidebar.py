"""
Вертикальная боковая навигация Lab_request.

Заменяет длинный горизонтальный ряд вкладок Notebook.
Переключение разделов делегируется колбэку on_select(section_id).
Сворачивание: ширина ~210 → ~64 (только короткие метки/иконки).
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from ...logging_setup import get_logger
from ..theme import COLORS, FONT_UI_SM

_log = get_logger("ui.sidebar")


@dataclass(frozen=True)
class NavItem:
    """Пункт навигации."""

    section_id: str
    label: str
    icon: str  # короткий текстовый глиф (единый стиль, без эмодзи-хаоса)
    group: int = 0


# Порядок как в макете: workflow → справочники → сервис
NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("pdf", "Заявки", "▢", 0),
    NavItem("calc", "Расчёты", "▦", 0),
    NavItem("kp", "КП", "▭", 0),
    NavItem("orders", "Заказы", "☰", 0),
    NavItem("marks", "Марки", "◇", 1),
    NavItem("orgs", "Организации", "◎", 1),
    NavItem("programs", "Программы", "⬡", 1),
    NavItem("history", "История", "↺", 2),
    NavItem("compare", "Сравнение", "⇅", 2),
    NavItem("settings", "Настройки", "⚙", 2),
)

# section_id → атрибут tab_* на приложении
SECTION_TO_TAB: dict[str, str] = {
    "pdf": "tab_pdf",
    "calc": "tab_calc",
    "kp": "tab_kp",
    "orders": "tab_orders",
    "marks": "tab_marks",
    "orgs": "tab_orgs",
    "programs": "tab_programs",
    "history": "tab_history",
    "compare": "tab_compare",
    "settings": "tab_settings",
    # Справочник — только через меню «Данные» (в сайдбаре нет по макету)
    "tests": "tab_tests",
}

TAB_TO_SECTION: dict[str, str] = {v: k for k, v in SECTION_TO_TAB.items()}


class Sidebar(tk.Frame):
    """
    Левая панель навигации.

    Активный пункт: светло-синий фон + синяя полоска слева + semibold.
    Неактивный: белый фон, hover-подсветка.
    """

    WIDTH_EXPANDED = 210
    WIDTH_COLLAPSED = 64

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_select: Callable[[str], None] | None = None,
        initial: str = "pdf",
    ) -> None:
        super().__init__(
            parent,
            bg=COLORS["sidebar_bg"],
            width=self.WIDTH_EXPANDED,
            highlightthickness=0,
            bd=0,
        )
        self.pack_propagate(False)
        self._on_select = on_select
        self._collapsed = False
        self._active = initial
        self._rows: dict[str, dict] = {}
        # PhotoImage refs (если появятся иконки) — держим, чтобы GC не убил
        self._images: list[tk.PhotoImage] = []

        # Brand
        brand = tk.Frame(self, bg=COLORS["sidebar_bg"], padx=14, pady=14)
        brand.pack(fill="x")
        self._brand_icon = tk.Label(
            brand,
            text="◆",
            bg=COLORS["sidebar_bg"],
            fg=COLORS["accent"],
            font=("Segoe UI Semibold", 12),
        )
        self._brand_icon.pack(side="left")
        self._brand_label = tk.Label(
            brand,
            text="Lab_request",
            bg=COLORS["sidebar_bg"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 11),
        )
        self._brand_label.pack(side="left", padx=(8, 0))

        tk.Frame(self, bg=COLORS["divider"], height=1).pack(fill="x")

        self._nav_host = tk.Frame(self, bg=COLORS["sidebar_bg"])
        self._nav_host.pack(fill="both", expand=True, pady=(8, 0))

        current_group = 0
        for item in NAV_ITEMS:
            if item.group != current_group:
                current_group = item.group
                sep = tk.Frame(self._nav_host, bg=COLORS["divider"], height=1)
                sep.pack(fill="x", padx=14, pady=8)

            row = tk.Frame(self._nav_host, bg=COLORS["sidebar_bg"], cursor="hand2")
            row.pack(fill="x", padx=8, pady=1)

            accent = tk.Frame(row, bg=COLORS["sidebar_bg"], width=3)
            accent.pack(side="left", fill="y")

            inner = tk.Frame(row, bg=COLORS["sidebar_bg"], padx=10, pady=9)
            inner.pack(side="left", fill="x", expand=True)

            icon_lbl = tk.Label(
                inner,
                text=item.icon,
                bg=COLORS["sidebar_bg"],
                fg=COLORS["sidebar_text"],
                font=("Segoe UI", 11),
                width=2,
            )
            icon_lbl.pack(side="left")
            text_lbl = tk.Label(
                inner,
                text=item.label,
                bg=COLORS["sidebar_bg"],
                fg=COLORS["sidebar_text"],
                font=("Segoe UI", 10),
                anchor="w",
            )
            text_lbl.pack(side="left", padx=(6, 0))

            self._rows[item.section_id] = {
                "item": item,
                "row": row,
                "accent": accent,
                "inner": inner,
                "icon": icon_lbl,
                "text": text_lbl,
            }

            def _click(_e=None, sid=item.section_id) -> None:
                self.select(sid, notify=True)

            def _enter(_e=None, sid=item.section_id) -> None:
                if sid != self._active:
                    self._paint_row(sid, hover=True)

            def _leave(_e=None, sid=item.section_id) -> None:
                if sid != self._active:
                    self._paint_row(sid, hover=False)

            for w in (row, accent, inner, icon_lbl, text_lbl):
                w.bind("<Button-1>", _click)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

        # Collapse control
        foot = tk.Frame(self, bg=COLORS["sidebar_bg"], padx=8, pady=10)
        foot.pack(side="bottom", fill="x")
        tk.Frame(self, bg=COLORS["divider"], height=1).pack(side="bottom", fill="x")
        self._collapse_btn = tk.Label(
            foot,
            text="«",
            bg=COLORS["sidebar_bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 12),
            cursor="hand2",
            padx=8,
            pady=4,
        )
        self._collapse_btn.pack(side="left")
        self._collapse_btn.bind("<Button-1>", lambda _e: self.toggle_collapse())

        self.select(initial, notify=False)
        _log.info(
            "Sidebar ready items=%s active=%s",
            len(NAV_ITEMS),
            initial,
            extra={"tag": "UI"},
        )

    def select(self, section_id: str, *, notify: bool = True) -> None:
        """Сделать пункт активным; опционально вызвать on_select."""
        if section_id not in self._rows and section_id != "tests":
            _log.warning("Sidebar unknown section=%s", section_id, extra={"tag": "UI"})
            return
        prev = self._active
        self._active = section_id
        if prev in self._rows:
            self._paint_row(prev, hover=False)
        if section_id in self._rows:
            self._paint_row(section_id, active=True)
        _log.debug("Sidebar select %s → %s", prev, section_id, extra={"tag": "UI"})
        if notify and self._on_select:
            self._on_select(section_id)

    def set_active(self, section_id: str) -> None:
        """Синхронизация извне (menubar / notebook), без повторного notify."""
        self.select(section_id, notify=False)

    def toggle_collapse(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        width = self.WIDTH_COLLAPSED if collapsed else self.WIDTH_EXPANDED
        self.configure(width=width)
        if collapsed:
            self._brand_label.pack_forget()
            self._collapse_btn.configure(text="»")
            for data in self._rows.values():
                data["text"].pack_forget()
        else:
            self._brand_label.pack(side="left", padx=(8, 0))
            self._collapse_btn.configure(text="«")
            for data in self._rows.values():
                data["text"].pack(side="left", padx=(6, 0))
        _log.info("Sidebar collapsed=%s width=%s", collapsed, width, extra={"tag": "UI"})

    def _paint_row(
        self,
        section_id: str,
        *,
        active: bool = False,
        hover: bool = False,
    ) -> None:
        data = self._rows.get(section_id)
        if not data:
            return
        if active or section_id == self._active:
            bg = COLORS["sidebar_active_bg"]
            fg = COLORS["sidebar_active_text"]
            accent_bg = COLORS["accent"]
            font = ("Segoe UI Semibold", 10)
        elif hover:
            bg = COLORS["sidebar_hover_bg"]
            fg = COLORS["sidebar_active_text"]
            accent_bg = COLORS["sidebar_hover_bg"]
            font = ("Segoe UI", 10)
        else:
            bg = COLORS["sidebar_bg"]
            fg = COLORS["sidebar_text"]
            accent_bg = COLORS["sidebar_bg"]
            font = ("Segoe UI", 10)

        for key in ("row", "inner", "icon", "text"):
            data[key].configure(bg=bg)
        data["icon"].configure(fg=fg)
        data["text"].configure(fg=fg, font=font)
        data["accent"].configure(bg=accent_bg)
