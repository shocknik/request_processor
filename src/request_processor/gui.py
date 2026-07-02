"""
gui.py — графический интерфейс (tkinter).

Запуск: request-processor gui
"""

from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .climatic_tests import climatic_settings_fields, is_climatic_code
from .test_rules import (
    CATEGORY_COLORS,
    CATEGORY_SHORT,
    category_sort_key,
    rule_type_label,
)
from .cost_calculator import calculate_cost, format_breakdown
from .models import ClimaticTestSettings, TestItemCreate
from .pdf_extractor import DEFAULT_OCR_DPI, extract_from_document
from .application_generator import generate_application_from_order
from .kp_generator import format_money, generate_kp_from_db, proposal_from_calculations
from .sqlite_repo import (
    DB_PATH_DEFAULT,
    GENERATED_DIR_DEFAULT,
    add_test_item,
    build_default_hours_map,
    get_calculations_for_kp,
    get_climatic_settings,
    get_last_document_extraction,
    get_organization_by_id,
    get_recent_calculations,
    init_db,
    list_cable_marks,
    list_organizations,
    list_test_items,
    save_calculation,
    save_cable_marks_from_matches,
    save_climatic_settings,
    save_document_extraction,
    save_organizations_from_extraction,
    update_organization,
    create_order_from_kp,
    list_orders,
    get_order_details,
    list_test_applications,
)

# Цветовая схема (современный flat UI)
COLORS = {
    "bg": "#eef1f8",
    "card": "#ffffff",
    "accent": "#4f46e5",
    "accent_hover": "#4338ca",
    "accent_light": "#e0e7ff",
    "text": "#111827",
    "muted": "#64748b",
    "border": "#d8dee9",
    "success": "#059669",
    "header_bg": "#1a1f36",
    "header_text": "#f8fafc",
    "header_muted": "#94a3b8",
    "header_accent": "#6366f1",
    "climatic_bg": "#eef2ff",
    "row_alt": "#f8fafc",
    "parse_bg": "#f5f7ff",
    "status_bg": "#e8ecf4",
    "tab_inactive": "#dce3f0",
    "shadow": "#c5cee0",
}

ORG_TYPE_LABELS: dict[str, str] = {
    "manufacturer": "Производитель",
    "certification_body": "Орган по сертификации",
    "testing_center": "Испытательный центр",
    "dealer": "Дилер",
    "unknown": "Не указан",
}
ORG_TYPE_VALUES = list(ORG_TYPE_LABELS.keys())


@dataclass
class CalcTestEntry:
    code: str
    name: str
    rule_type: str
    hours_key: str | None
    hours_var: tk.StringVar | None = None
    row_frame: ttk.Frame | None = field(default=None, repr=False)


class RequestProcessorApp(tk.Tk):
    def __init__(self, db_path: Path = DB_PATH_DEFAULT) -> None:
        super().__init__()
        self.db_path = Path(db_path)
        self.generated_dir = GENERATED_DIR_DEFAULT
        self.title("Обработка заявок на испытания кабелей")
        self.geometry("1200x820")
        self.minsize(1020, 700)
        self.configure(bg=COLORS["bg"])

        self._tests_by_code: dict[str, dict] = {}
        self._calc_entries: list[CalcTestEntry] = []
        self.notebook: ttk.Notebook | None = None
        self._last_document_extraction_id: int | None = None
        self._last_manufacturer_name: str = ""

        self._ensure_db()
        self._setup_theme()
        self._build_ui()
        self._load_history()
        self._load_tests()
        self._load_cable_marks()
        self._load_settings()
        self._load_kp_calculations()
        self._load_organizations()
        self._refresh_parse_info_panel()
        self._load_orders_table()

    def _accent_button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        """Основная кнопка действия — полный текст, контрастный фон."""
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["accent"],
            fg="white",
            activebackground=COLORS["accent_hover"],
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=18,
            pady=9,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )

    def _secondary_button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        """Вторичная кнопка — контур, без заливки."""
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["card"],
            fg=COLORS["text"],
            activebackground=COLORS["accent_light"],
            activeforeground=COLORS["accent"],
            font=("Segoe UI", 10),
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )

    def _ensure_db(self) -> None:
        if not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            init_db(self.db_path)
        else:
            from .sqlite_repo import _seed_default_settings, migrate_db

            migrate_db(self.db_path)
            _seed_default_settings(self.db_path)

    def _setup_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=COLORS["card"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 17, "bold"), foreground=COLORS["header_text"])
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), foreground=COLORS["header_muted"])
        style.configure("Header.TFrame", background=COLORS["header_bg"])
        style.configure(
            "TButton",
            font=("Segoe UI", 10),
            padding=(12, 7),
            background=COLORS["card"],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", COLORS["accent_light"]), ("pressed", COLORS["border"])],
            foreground=[("active", COLORS["accent"])],
        )
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("TLabelframe", background=COLORS["bg"])
        style.configure("TLabelframe.Label", background=COLORS["bg"], font=("Segoe UI", 10, "bold"))
        style.configure("Card.TLabelframe", background=COLORS["card"])
        style.configure("Card.TLabelframe.Label", background=COLORS["card"], font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=30, background=COLORS["card"])
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#e2e8f0")
        style.map("Treeview", background=[("selected", COLORS["accent"])], foreground=[("selected", "white")])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0, tabmargins=(4, 4, 4, 0))
        style.configure(
            "TNotebook.Tab",
            font=("Segoe UI", 10),
            padding=(14, 9),
            background=COLORS["tab_inactive"],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["card"]), ("!selected", COLORS["tab_inactive"])],
            foreground=[("selected", COLORS["accent"]), ("!selected", COLORS["muted"])],
            font=[("selected", ("Segoe UI", 10, "bold")), ("!selected", ("Segoe UI", 10))],
            expand=[("selected", [1, 1, 1, 0])],
        )
        style.configure("Status.TLabel", background=COLORS["status_bg"], font=("Segoe UI", 9))
        style.configure("TEntry", font=("Segoe UI", 10))
        style.configure("TSpinbox", font=("Segoe UI", 10))

    def _build_ui(self) -> None:
        header_wrap = tk.Frame(self, bg=COLORS["header_bg"])
        header_wrap.pack(fill="x")

        header = tk.Frame(header_wrap, bg=COLORS["header_bg"], padx=22, pady=16)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Испытания кабельной продукции",
            bg=COLORS["header_bg"],
            fg=COLORS["header_text"],
            font=("Segoe UI Semibold", 19, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            text="1 → 2 → 3 → 4",
            bg=COLORS["header_accent"],
            fg="white",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=3,
        ).pack(side="left", padx=(14, 0))
        tk.Label(
            header,
            text="заявка  →  расчёт  →  КП  →  заказ",
            bg=COLORS["header_bg"],
            fg=COLORS["header_muted"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(12, 0))

        tk.Frame(header_wrap, bg=COLORS["header_accent"], height=3).pack(fill="x")

        parse_bar = tk.Frame(self, bg=COLORS["parse_bg"], padx=20, pady=10)
        parse_bar.pack(fill="x")
        tk.Frame(parse_bar, bg=COLORS["accent"], width=4).pack(side="left", fill="y", padx=(0, 12))
        parse_inner = tk.Frame(parse_bar, bg=COLORS["parse_bg"])
        parse_inner.pack(side="left", fill="x", expand=True)
        self.parse_info_var = tk.StringVar(value="Документ не обработан — начните с вкладки «1. Заявка»")
        tk.Label(
            parse_inner,
            textvariable=self.parse_info_var,
            bg=COLORS["parse_bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w")

        self.status = tk.StringVar(value="Готово")
        status_wrap = tk.Frame(self, bg=COLORS["status_bg"], height=32)
        status_wrap.pack(side="bottom", fill="x")
        status_wrap.pack_propagate(False)
        ttk.Label(
            status_wrap,
            textvariable=self.status,
            anchor="w",
            padding=(18, 6),
            style="Status.TLabel",
        ).pack(fill="both", expand=True)

        content_wrap = tk.Frame(self, bg=COLORS["bg"], padx=14, pady=10)
        content_wrap.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(content_wrap, padding=(6, 8, 6, 10))
        self.notebook.pack(fill="both", expand=True)

        self.tab_pdf = ttk.Frame(self.notebook, padding=10)
        self.tab_calc = ttk.Frame(self.notebook, padding=10)
        self.tab_kp = ttk.Frame(self.notebook, padding=10)
        self.tab_orders = ttk.Frame(self.notebook, padding=10)
        self.tab_marks = ttk.Frame(self.notebook, padding=10)
        self.tab_orgs = ttk.Frame(self.notebook, padding=10)
        self.tab_tests = ttk.Frame(self.notebook, padding=10)
        self.tab_history = ttk.Frame(self.notebook, padding=10)
        self.tab_settings = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.tab_pdf, text="  1. Заявка  ")
        self.notebook.add(self.tab_calc, text="  2. Расчёт  ")
        self.notebook.add(self.tab_kp, text="  3. КП  ")
        self.notebook.add(self.tab_orders, text="  4. Заказы  ")
        self.notebook.add(self.tab_marks, text="  5. Марки  ")
        self.notebook.add(self.tab_orgs, text="  6. Организации  ")
        self.notebook.add(self.tab_tests, text="  7. Справочник  ")
        self.notebook.add(self.tab_history, text="  8. История  ")
        self.notebook.add(self.tab_settings, text="  9. Настройки  ")

        self._build_pdf_tab()
        self._build_calc_tab()
        self._build_kp_tab()
        self._build_orders_tab()
        self._build_marks_tab()
        self._build_orgs_tab()
        self._build_tests_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        if not self.notebook:
            return
        selected = self.notebook.index(self.notebook.select())
        if selected == self.notebook.index(self.tab_kp):
            self._load_kp_calculations()
        elif selected == self.notebook.index(self.tab_orgs):
            self._load_orgs_table()
        elif selected == self.notebook.index(self.tab_orders):
            self._load_orders_table()

    def _build_calc_tab(self) -> None:
        top = ttk.LabelFrame(self.tab_calc, text="Марка кабеля", padding=12, style="Card.TLabelframe")
        top.pack(fill="x", pady=(0, 10))
        top.configure(style="Card.TLabelframe")

        inner = ttk.Frame(top, style="Card.TFrame")
        inner.pack(fill="x")
        self.mark_var = tk.StringVar()
        mark_entry = ttk.Entry(inner, textvariable=self.mark_var, font=("Segoe UI", 11))
        mark_entry.pack(fill="x", ipady=4)
        ttk.Label(
            inner,
            text="Пример: ВВГ-Пнг(А) 3х4ок(М,РЕ)-0,66",
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        mid = ttk.PanedWindow(self.tab_calc, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=(0, 10))

        left = ttk.LabelFrame(mid, text="Выбранные испытания", padding=8, style="Card.TLabelframe")
        mid.add(left, weight=1)

        list_header = ttk.Frame(left, style="Card.TFrame")
        list_header.pack(fill="x", pady=(0, 6))
        ttk.Label(list_header, text="Испытание", style="Card.TLabel", width=36).pack(side="left")
        ttk.Label(list_header, text="Правило", style="Card.TLabel", width=10).pack(side="left")
        ttk.Label(list_header, text="Часы", style="Card.TLabel", width=8).pack(side="left")
        ttk.Label(
            left,
            text="ПКМ по строке — удалить испытание",
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(0, 4))

        canvas_frame = ttk.Frame(left, style="Card.TFrame")
        canvas_frame.pack(fill="both", expand=True)

        self._calc_canvas = tk.Canvas(
            canvas_frame,
            bg=COLORS["card"],
            highlightthickness=0,
            borderwidth=0,
        )
        calc_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self._calc_canvas.yview)
        self.calc_tests_inner = ttk.Frame(self._calc_canvas, style="Card.TFrame")
        self.calc_tests_inner.bind(
            "<Configure>",
            lambda e: self._calc_canvas.configure(scrollregion=self._calc_canvas.bbox("all")),
        )
        self._calc_canvas.create_window((0, 0), window=self.calc_tests_inner, anchor="nw")
        self._calc_canvas.configure(yscrollcommand=calc_scroll.set)
        self._calc_canvas.pack(side="left", fill="both", expand=True)
        calc_scroll.pack(side="right", fill="y")

        self._calc_empty_label = ttk.Label(
            self.calc_tests_inner,
            text="Дважды кликните испытание\nво вкладке «7. Справочник»",
            style="CardMuted.TLabel",
            justify="center",
        )
        self._calc_empty_label.pack(pady=40)

        list_btns = ttk.Frame(left, style="Card.TFrame")
        list_btns.pack(fill="x", pady=(8, 0))
        ttk.Button(list_btns, text="Удалить последнее", command=self._remove_selected_calc_test).pack(
            side="left"
        )
        ttk.Button(list_btns, text="Очистить список", command=self._clear_calc_tests).pack(
            side="left", padx=8
        )

        right = ttk.LabelFrame(mid, text="Результат расчёта", padding=8, style="Card.TLabelframe")
        mid.add(right, weight=2)

        self.calc_output = scrolledtext.ScrolledText(
            right,
            height=20,
            state="disabled",
            font=("Consolas", 10),
            bg="#f8fafc",
            fg=COLORS["text"],
            relief="flat",
            padx=8,
            pady=8,
        )
        self.calc_output.pack(fill="both", expand=True)

        btns = ttk.Frame(self.tab_calc)
        btns.pack(fill="x")
        self._accent_button(btns, "Рассчитать", self._run_calculate).pack(side="left")
        ttk.Button(btns, text="Очистить всё", command=self._clear_calc).pack(side="left", padx=10)
        ttk.Label(
            btns,
            text="Климатические испытания — укажите часы выдержки в списке слева",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

    def _build_pdf_tab(self) -> None:
        top = ttk.Frame(self.tab_pdf)
        top.pack(fill="x")

        self.pdf_path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.pdf_path_var).pack(side="left", fill="x", expand=True, ipady=3)
        ttk.Button(top, text="Обзор…", command=self._browse_pdf).pack(side="left", padx=6)
        self._accent_button(top, "Извлечь", self._run_extract_pdf).pack(side="left", padx=(0, 4))

        opts = ttk.Frame(self.tab_pdf)
        opts.pack(fill="x", pady=8)
        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="OCR для сканов", variable=self.ocr_var).pack(side="left")
        ttk.Label(opts, text=f"DPI: {DEFAULT_OCR_DPI}", style="Muted.TLabel").pack(side="left", padx=12)
        self.save_marks_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Сохранять марки в БД", variable=self.save_marks_var).pack(side="left")
        self.save_orgs_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Сохранять организации в БД", variable=self.save_orgs_var).pack(
            side="left", padx=(12, 0)
        )

        mid = ttk.PanedWindow(self.tab_pdf, orient="horizontal")
        mid.pack(fill="both", expand=True)

        left = ttk.LabelFrame(mid, text="Найденные марки", padding=8, style="Card.TLabelframe")
        mid.add(left, weight=1)
        self.marks_list = tk.Listbox(
            left,
            height=14,
            font=("Segoe UI", 10),
            bg=COLORS["card"],
            fg=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        self.marks_list.pack(fill="both", expand=True)
        self.marks_list.bind("<Double-Button-1>", lambda e: self._use_mark_in_calc())
        ttk.Button(left, text="→ В расчёт", command=self._use_mark_in_calc).pack(pady=(8, 0))

        right = ttk.LabelFrame(mid, text="Сводка", padding=8, style="Card.TLabelframe")
        mid.add(right, weight=1)
        self.pdf_output = scrolledtext.ScrolledText(
            right, height=14, state="disabled", font=("Segoe UI", 10), bg="#f8fafc", relief="flat"
        )
        self.pdf_output.pack(fill="both", expand=True)

    def _build_marks_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_marks)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_cable_marks).pack(side="left")
        self.marks_search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.marks_search_var, width=32).pack(side="left", padx=8, ipady=2)
        ttk.Button(toolbar, text="Поиск", command=self._load_cable_marks).pack(side="left")

        cols = ("full_mark", "brand", "fire_class", "cores", "element", "size", "document")
        self.cable_marks_tree = ttk.Treeview(self.tab_marks, columns=cols, show="headings", height=20)
        for col, title, width in (
            ("full_mark", "Полная марка", 260),
            ("brand", "Марка", 80),
            ("fire_class", "Пожарный класс", 90),
            ("cores", "ТПЖ", 50),
            ("element", "Элемент", 70),
            ("size", "Размер", 80),
            ("document", "Документ", 180),
        ):
            self.cable_marks_tree.heading(col, text=title)
            self.cable_marks_tree.column(col, width=width, anchor="w")
        self.cable_marks_tree.pack(fill="both", expand=True, pady=(8, 0))
        self.cable_marks_tree.bind("<Double-Button-1>", lambda e: self._use_db_mark_in_calc())
        ttk.Button(self.tab_marks, text="→ В расчёт", command=self._use_db_mark_in_calc).pack(
            anchor="w", pady=6
        )

    def _build_kp_tab(self) -> None:
        form = ttk.LabelFrame(
            self.tab_kp,
            text="Вводная информация",
            padding=12,
            style="Card.TLabelframe",
        )
        form.pack(fill="x", pady=(0, 10))

        grid = ttk.Frame(form, style="Card.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Заказчик:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.kp_customer_var = tk.StringVar(value="")
        self.kp_customer_combo = ttk.Combobox(
            grid,
            textvariable=self.kp_customer_var,
            font=("Segoe UI", 10),
        )
        self.kp_customer_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4, ipady=2)
        ttk.Button(grid, text="↻", width=3, command=self._load_organizations).grid(
            row=0, column=2, padx=(4, 0), pady=4
        )

        ttk.Label(grid, text="Предмет:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.kp_subject_var = tk.StringVar(value="Проведение периодических испытаний")
        ttk.Entry(grid, textvariable=self.kp_subject_var, font=("Segoe UI", 10)).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=4, ipady=2
        )

        ttk.Label(grid, text="Примечание:", style="Card.TLabel").grid(
            row=2, column=0, sticky="nw", pady=4
        )
        self.kp_note_text = scrolledtext.ScrolledText(grid, height=3, font=("Segoe UI", 10))
        self.kp_note_text.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

        action = ttk.Frame(self.tab_kp)
        action.pack(fill="x", pady=(0, 8))

        self._accent_button(action, "Сформировать КП", self._run_generate_kp).pack(side="left")
        ttk.Button(action, text="Выбрать все", command=self._select_all_kp_calcs).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(action, text="Обновить список", command=self._load_kp_calculations).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            action,
            text=f"Папка: {self.generated_dir}",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

        self.kp_preview_var = tk.StringVar(value="Выберите расчёты из списка (Ctrl+клик — несколько)")
        ttk.Label(
            self.tab_kp,
            textvariable=self.kp_preview_var,
            font=("Segoe UI", 10, "bold"),
            foreground=COLORS["accent"],
        ).pack(anchor="w", pady=(0, 6))

        mid = ttk.LabelFrame(
            self.tab_kp,
            text="Сохранённые расчёты (по одной марке на строку)",
            padding=8,
            style="Card.TLabelframe",
        )
        mid.pack(fill="both", expand=True)

        cols = ("id", "mark", "without_vat", "with_vat", "date")
        self.kp_calc_tree = ttk.Treeview(
            mid,
            columns=cols,
            show="headings",
            height=12,
            selectmode="extended",
        )
        for col, title, width, anchor in (
            ("id", "ID", 50, "center"),
            ("mark", "Марка", 420, "w"),
            ("without_vat", "Без НДС", 100, "e"),
            ("with_vat", "С НДС", 100, "e"),
            ("date", "Дата", 130, "w"),
        ):
            self.kp_calc_tree.heading(col, text=title)
            self.kp_calc_tree.column(col, width=width, anchor=anchor)
        self.kp_calc_tree.pack(fill="both", expand=True)
        self.kp_calc_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_kp_preview())
        self.kp_calc_tree.bind("<Double-Button-1>", lambda _e: self._run_generate_kp())
        self.tab_kp.bind("<Return>", lambda _e: self._run_generate_kp())

    def _build_orders_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_orders)
        toolbar.pack(fill="x", pady=(0, 8))
        self._accent_button(toolbar, "Сформировать заявку", self._generate_order_application).pack(
            side="left"
        )
        self._secondary_button(toolbar, "Открыть КП", self._open_selected_order_kp).pack(
            side="left", padx=(8, 0)
        )
        self._secondary_button(toolbar, "Открыть заявку", self._open_selected_order_application).pack(
            side="left", padx=(6, 0)
        )
        self._secondary_button(toolbar, "Печать КП", self._print_selected_order_kp).pack(
            side="left", padx=(6, 0)
        )
        self._secondary_button(toolbar, "Печать заявку", self._print_selected_order_application).pack(
            side="left", padx=(6, 0)
        )
        self._secondary_button(toolbar, "Обновить", self._load_orders_table).pack(side="left", padx=(6, 0))
        ttk.Label(
            toolbar,
            text="Клик — детали; двойной клик — открыть КП",
            style="Muted.TLabel",
        ).pack(side="right")

        paned = ttk.PanedWindow(self.tab_orders, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(
            paned, text="Сохранённые заказы", padding=8, style="Card.TLabelframe"
        )
        paned.add(left, weight=2)
        cols = ("id", "date", "customer", "marks", "total", "status")
        self.orders_tree = ttk.Treeview(
            left, columns=cols, show="headings", height=16, selectmode="browse"
        )
        for col, title, width, anchor in (
            ("id", "№", 45, "center"),
            ("date", "Дата", 130, "w"),
            ("customer", "Заказчик", 240, "w"),
            ("marks", "Марок", 55, "center"),
            ("total", "С НДС, ₽", 110, "e"),
            ("status", "Статус", 100, "w"),
        ):
            self.orders_tree.heading(col, text=title, anchor=anchor)
            self.orders_tree.column(col, width=width, anchor=anchor)
        self.orders_tree.pack(fill="both", expand=True)
        self.orders_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_order_details())
        self.orders_tree.bind("<Double-Button-1>", lambda _e: self._open_selected_order_kp())

        right = ttk.LabelFrame(paned, text="Информация о заказе", padding=8, style="Card.TLabelframe")
        paned.add(right, weight=1)
        self.order_details = scrolledtext.ScrolledText(
            right,
            height=20,
            state="disabled",
            font=("Segoe UI", 10),
            bg="#f8fafc",
            relief="flat",
            padx=8,
            pady=8,
        )
        self.order_details.pack(fill="both", expand=True)

    def _build_orgs_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_orgs)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Обновить", command=self._load_orgs_table).pack(side="left")
        ttk.Button(toolbar, text="Редактировать…", command=self._edit_selected_organization).pack(
            side="left", padx=6
        )
        self.orgs_search_var = tk.StringVar()
        self.orgs_search_var.trace_add("write", lambda *_: self._load_orgs_table())
        ttk.Entry(toolbar, textvariable=self.orgs_search_var, width=36).pack(
            side="left", padx=(12, 0), ipady=2
        )
        ttk.Label(toolbar, text="Двойной клик — редактирование", style="Muted.TLabel").pack(
            side="right"
        )

        cols = ("name", "inn", "org_type", "accredited", "address", "phone", "fsa")
        self.orgs_tree = ttk.Treeview(
            self.tab_orgs,
            columns=cols,
            show="headings",
            height=20,
            selectmode="browse",
        )
        for col, title, width, anchor in (
            ("name", "Название", 280, "w"),
            ("inn", "ИНН", 110, "w"),
            ("org_type", "Тип", 130, "w"),
            ("accredited", "Аккред.", 70, "center"),
            ("address", "Адрес", 220, "w"),
            ("phone", "Телефон", 120, "w"),
            ("fsa", "Реестр ФСА", 150, "w"),
        ):
            self.orgs_tree.heading(col, text=title, anchor=anchor)
            self.orgs_tree.column(col, width=width, anchor=anchor)
        self.orgs_tree.pack(fill="both", expand=True)
        self.orgs_tree.bind("<Double-Button-1>", lambda _e: self._edit_selected_organization())

    def _build_history_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_history)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_history).pack(side="left")

        cols = ("id", "created_at", "mark", "total", "source")
        self.history_tree = ttk.Treeview(self.tab_history, columns=cols, show="headings", height=20)
        for col, title, width in (
            ("id", "ID", 50),
            ("created_at", "Дата", 140),
            ("mark", "Марка", 400),
            ("total", "С НДС, ₽", 110),
            ("source", "Источник", 80),
        ):
            self.history_tree.heading(col, text=title)
            self.history_tree.column(col, width=width, anchor="w")
        self.history_tree.pack(fill="both", expand=True, pady=(8, 0))

    def _build_tests_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_tests)
        toolbar.pack(fill="x", pady=(0, 8))

        ttk.Button(toolbar, text="Обновить", command=self._load_tests).pack(side="left")
        ttk.Button(toolbar, text="Добавить…", command=self._add_test_dialog).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Развернуть все", command=self._expand_all_categories).pack(
            side="left", padx=6
        )
        ttk.Button(toolbar, text="Свернуть все", command=self._collapse_all_categories).pack(
            side="left"
        )

        self.tests_search_var = tk.StringVar()
        self.tests_search_var.trace_add("write", lambda *_: self._load_tests())
        search_frame = ttk.Frame(self.tab_tests)
        search_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(search_frame, text="Поиск:").pack(side="left")
        ttk.Entry(search_frame, textvariable=self.tests_search_var, width=40).pack(
            side="left", padx=8, ipady=2
        )
        self.calc_count_var = tk.StringVar(value="В расчёте: 0")
        ttk.Label(search_frame, textvariable=self.calc_count_var, style="Muted.TLabel").pack(
            side="right", padx=(8, 0)
        )
        ttk.Label(search_frame, text="Двойной клик — добавить в расчёт", style="Muted.TLabel").pack(
            side="right"
        )

        cols = ("price", "rule", "hours")
        self.tests_tree = ttk.Treeview(
            self.tab_tests,
            columns=cols,
            show="tree headings",
            height=22,
            selectmode="browse",
        )
        self.tests_tree.heading("#0", text="Категория / Испытание", anchor="w")
        self.tests_tree.column("#0", width=480, minwidth=280)
        for col, title, width, anchor in (
            ("price", "Цена, ₽", 80, "e"),
            ("rule", "Правило", 90, "center"),
            ("hours", "Часы", 55, "e"),
        ):
            self.tests_tree.heading(col, text=title, anchor=anchor)
            self.tests_tree.column(col, width=width, anchor=anchor)
        self.tests_tree.pack(fill="both", expand=True)

        self.tests_tree.tag_configure("category", font=("Segoe UI", 10, "bold"))
        self.tests_tree.tag_configure("climatic", background=COLORS["climatic_bg"])
        self._category_tags: dict[str, str] = {}
        for cat, color in CATEGORY_COLORS.items():
            tag = "cat_" + re.sub(r"[^\w]", "_", cat)
            self._category_tags[cat] = tag
            self.tests_tree.tag_configure(tag, background=color)

        self.tests_tree.bind("<Double-1>", self._on_test_double_click)

    def _build_settings_tab(self) -> None:
        frame = ttk.LabelFrame(
            self.tab_settings,
            text="Время выдержки климатических испытаний (часы по умолчанию)",
            padding=16,
            style="Card.TLabelframe",
        )
        frame.pack(fill="x", pady=8)

        self.setting_vars: dict[str, tk.StringVar] = {}
        for row, (key, label) in enumerate(climatic_settings_fields()):
            ttk.Label(frame, text=label + ":", style="Card.TLabel").grid(
                row=row, column=0, sticky="w", pady=8, padx=(0, 12)
            )
            var = tk.StringVar()
            self.setting_vars[key] = var
            ttk.Spinbox(
                frame,
                textvariable=var,
                from_=0.5,
                to=9999,
                increment=0.5,
                width=10,
                font=("Segoe UI", 10),
            ).grid(row=row, column=1, sticky="w", pady=8)
            ttk.Label(frame, text=f"ключ: {key}", style="CardMuted.TLabel").grid(
                row=row, column=2, sticky="w", padx=12
            )

        ttk.Button(frame, text="Сохранить настройки", style="Accent.TButton", command=self._save_settings).grid(
            row=len(climatic_settings_fields()),
            column=0,
            columnspan=2,
            sticky="w",
            pady=(16, 0),
        )

        hint = scrolledtext.ScrolledText(
            self.tab_settings,
            height=8,
            state="disabled",
            font=("Segoe UI", 10),
            bg="#f8fafc",
            relief="flat",
        )
        hint.pack(fill="both", expand=True, pady=8)
        self._set_text(
            hint,
            "Эти значения подставляются при добавлении климатического испытания в расчёт.\n"
            "В списке «Выбранные испытания» часы можно изменить для конкретного расчёта.\n\n"
            "Все климатические испытания — time_based (база + стоимость за час выдержки).",
        )

    def _default_hours_for(self, code: str, hours_key: str | None, rule_params: dict) -> float:
        defaults = build_default_hours_map(self.db_path)
        key = hours_key or code
        if key in defaults:
            return defaults[key]
        return float(rule_params.get("default_hours", 2))

    def _hide_calc_empty_hint(self) -> None:
        if self._calc_empty_label.winfo_ismapped():
            self._calc_empty_label.pack_forget()

    def _show_calc_empty_hint_if_needed(self) -> None:
        if not self._calc_entries and not self._calc_empty_label.winfo_ismapped():
            self._calc_empty_label.pack(pady=40)

    def _add_test_to_calc(self, code: str) -> None:
        test = self._tests_by_code.get(code)
        if not test:
            messagebox.showwarning("Справочник", f"Испытание «{code}» не найдено.")
            return

        rule_params = json.loads(test.get("rule_params") or "{}")
        rule_type = test["rule_type"]
        hours_key = rule_params.get("hours_key") if rule_type == "time_based" else None

        hours_var: tk.StringVar | None = None
        if rule_type == "time_based":
            hours_var = tk.StringVar(
                value=str(self._default_hours_for(code, hours_key, rule_params))
            )

        entry = CalcTestEntry(
            code=code,
            name=test["name"],
            rule_type=rule_type,
            hours_key=hours_key,
            hours_var=hours_var,
        )
        self._calc_entries.append(entry)
        self._render_calc_entry(entry, len(self._calc_entries) - 1)
        self._hide_calc_empty_hint()

        self._update_calc_count_label()
        self.status.set(f"Добавлено в расчёт: {test['name'][:50]} (остаётесь в справочнике)")

    def _render_calc_entry(self, entry: CalcTestEntry, index: int) -> None:
        bg_style = "Card.TFrame"
        row = ttk.Frame(self.calc_tests_inner, style=bg_style, padding=(4, 3))
        row.pack(fill="x")

        is_climatic = is_climatic_code(entry.code) or entry.rule_type == "time_based"
        if is_climatic:
            climatic_frame = tk.Frame(row, bg=COLORS["climatic_bg"], padx=4, pady=4)
            climatic_frame.pack(fill="x")
            inner = ttk.Frame(climatic_frame, style=bg_style)
            inner.pack(fill="x")
        else:
            inner = row

        name_lbl = ttk.Label(
            inner,
            text=entry.name[:42],
            style="Card.TLabel",
            width=36,
            anchor="w",
        )
        name_lbl.pack(side="left")

        rule_lbl = ttk.Label(
            inner,
            text=rule_type_label(entry.rule_type),
            style="CardMuted.TLabel",
            width=10,
            anchor="center",
        )
        rule_lbl.pack(side="left", padx=(4, 0))

        if entry.rule_type == "time_based" and entry.hours_var is not None:
            hours_frame = ttk.Frame(inner, style=bg_style)
            hours_frame.pack(side="left", padx=(4, 0))
            ttk.Label(hours_frame, text="⏱", style="Card.TLabel").pack(side="left")
            spin = ttk.Spinbox(
                hours_frame,
                textvariable=entry.hours_var,
                from_=0.5,
                to=9999,
                increment=0.5,
                width=7,
                font=("Segoe UI", 10),
            )
            spin.pack(side="left", padx=(2, 0))
            ttk.Label(hours_frame, text="ч", style="CardMuted.TLabel").pack(side="left", padx=(2, 0))
        else:
            ttk.Label(inner, text="—", style="CardMuted.TLabel", width=8).pack(side="left")

        entry.row_frame = row
        for widget in (row, inner, name_lbl):
            widget.bind("<Button-3>", lambda e, ent=entry: self._show_calc_context_menu(e, ent))

    def _show_calc_context_menu(self, event: tk.Event, entry: CalcTestEntry) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Удалить из расчёта",
            command=lambda: self._remove_calc_entry(entry),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _remove_calc_entry(self, entry: CalcTestEntry) -> None:
        if entry not in self._calc_entries:
            return
        self._calc_entries.remove(entry)
        if entry.row_frame:
            entry.row_frame.destroy()
        self._show_calc_empty_hint_if_needed()
        self._update_calc_count_label()
        self.status.set(f"Удалено: {entry.name[:40]}")

    def _remove_selected_calc_test(self) -> None:
        if self._calc_entries:
            self._remove_calc_entry(self._calc_entries[-1])

    def _clear_calc_tests(self) -> None:
        self._calc_entries.clear()
        for child in self.calc_tests_inner.winfo_children():
            if child is not self._calc_empty_label:
                child.destroy()
        self._show_calc_empty_hint_if_needed()
        self._update_calc_count_label()

    def _update_calc_count_label(self) -> None:
        if hasattr(self, "calc_count_var"):
            self.calc_count_var.set(f"В расчёте: {len(self._calc_entries)}")

    def _on_test_double_click(self, event: tk.Event) -> None:
        item = self.tests_tree.identify_row(event.y)
        if not item or not str(item).startswith("test::"):
            return
        code = str(item).removeprefix("test::")
        self._add_test_to_calc(code)

    def _expand_all_categories(self) -> None:
        for item in self.tests_tree.get_children(""):
            self.tests_tree.item(item, open=True)

    def _collapse_all_categories(self) -> None:
        for item in self.tests_tree.get_children(""):
            self.tests_tree.item(item, open=False)

    def _build_hours_map(self) -> dict[str, float]:
        hours = build_default_hours_map(self.db_path)
        for entry in self._calc_entries:
            if entry.rule_type == "time_based" and entry.hours_var and entry.hours_key:
                try:
                    hours[entry.hours_key] = float(entry.hours_var.get().replace(",", "."))
                except ValueError:
                    pass
        return hours

    def _set_text(self, widget: scrolledtext.ScrolledText, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _run_calculate(self) -> None:
        mark = self.mark_var.get().strip()
        if not mark:
            messagebox.showwarning("Расчёт", "Укажите марку кабеля.")
            return
        if not self._calc_entries:
            messagebox.showwarning("Расчёт", "Добавьте испытания из справочника (двойной клик).")
            return

        test_list = [e.code for e in self._calc_entries]
        hours = self._build_hours_map()
        self.status.set("Расчёт…")

        def work() -> None:
            try:
                calc = calculate_cost(mark, test_list, hours, self.db_path)
                calc_id = save_calculation(calc, self.db_path)
                text = format_breakdown(calc) + f"\n\n✓ Сохранено в БД (id={calc_id})"
                self.after(0, lambda: self._set_text(self.calc_output, text))
                self.after(0, self._load_history)
                self.after(0, self._load_kp_calculations)
                self.after(0, lambda: self.status.set("Расчёт выполнен"))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Ошибка расчёта", str(exc)))
                self.after(0, lambda: self.status.set("Ошибка"))

        threading.Thread(target=work, daemon=True).start()

    def _clear_calc(self) -> None:
        self.mark_var.set("")
        self._clear_calc_tests()
        self._set_text(self.calc_output, "")

    def _format_parse_info(
        self,
        *,
        file_name: str,
        source_type: str,
        marks_count: int,
        customer_name: str = "",
        manufacturer_name: str = "",
        ocr_used: bool = False,
        page_count: int = 0,
        extracted_at: str = "",
    ) -> str:
        parts = [
            f"📄 {file_name}",
            source_type.upper(),
        ]
        if page_count:
            parts.append(f"{page_count} стр.")
        parts.append(f"{marks_count} марок")
        if customer_name:
            parts.append(f"заказчик: {customer_name}")
        if manufacturer_name and manufacturer_name != customer_name:
            parts.append(f"производитель: {manufacturer_name}")
        if ocr_used:
            parts.append("OCR")
        if extracted_at:
            parts.append(extracted_at[:16].replace("T", " "))
        return "  ·  ".join(parts)

    def _refresh_parse_info_panel(self) -> None:
        row = get_last_document_extraction(self.db_path)
        if not row:
            self.parse_info_var.set("Заявка не обработана — вкладка «1. Заявка»")
            return
        file_name = Path(row["source_path"]).name
        self.parse_info_var.set(
            self._format_parse_info(
                file_name=file_name,
                source_type=row.get("source_type") or "unknown",
                marks_count=int(row.get("marks_count") or 0),
                customer_name=row.get("customer_name") or "",
                manufacturer_name=row.get("manufacturer_name") or "",
                extracted_at=row.get("extracted_at") or "",
            )
        )

    def _load_orgs_table(self) -> None:
        if not hasattr(self, "orgs_tree"):
            return
        for item in self.orgs_tree.get_children():
            self.orgs_tree.delete(item)
        search = (
            self.orgs_search_var.get().strip() or None
            if hasattr(self, "orgs_search_var")
            else None
        )
        for row in list_organizations(search=search, limit=300, db_path=self.db_path):
            org_type = ORG_TYPE_LABELS.get(row.get("org_type") or "unknown", row.get("org_type"))
            addr = row.get("address") or ""
            if row.get("postal_code"):
                addr = f"{row['postal_code']}, {addr}".strip(", ")
            self.orgs_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["name"],
                    row.get("inn") or "",
                    org_type,
                    "да" if row.get("is_accredited") else "нет",
                    addr[:80],
                    row.get("phone") or "",
                    row.get("fsa_registry_number") or "",
                ),
            )

    def _load_organizations(self) -> None:
        rows = list_organizations(limit=200, db_path=self.db_path)
        names = [row["name"] for row in rows]
        self.kp_customer_combo["values"] = names
        self._load_orgs_table()

    def _edit_selected_organization(self) -> None:
        if not hasattr(self, "orgs_tree"):
            return
        sel = self.orgs_tree.selection()
        if not sel:
            messagebox.showinfo("Организации", "Выберите организацию в таблице.")
            return
        org_id = int(sel[0])
        row = get_organization_by_id(org_id, self.db_path)
        if not row:
            messagebox.showerror("Организации", "Запись не найдена в БД.")
            return
        self._open_organization_editor(row)

    def _open_organization_editor(self, row: dict) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(f"Организация — {row.get('name', '')[:40]}")
        dialog.geometry("520x520")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()

        fields: dict[str, tk.Variable] = {
            "name": tk.StringVar(value=row.get("name") or ""),
            "inn": tk.StringVar(value=row.get("inn") or ""),
            "kpp": tk.StringVar(value=row.get("kpp") or ""),
            "postal_code": tk.StringVar(value=row.get("postal_code") or ""),
            "address": tk.StringVar(value=row.get("address") or ""),
            "phone": tk.StringVar(value=row.get("phone") or ""),
            "email": tk.StringVar(value=row.get("email") or ""),
            "fsa_registry_number": tk.StringVar(value=row.get("fsa_registry_number") or ""),
            "org_type": tk.StringVar(value=row.get("org_type") or "unknown"),
            "is_accredited": tk.BooleanVar(value=bool(row.get("is_accredited"))),
        }

        form = ttk.Frame(dialog, padding=12)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        labels = (
            ("Название:", "name"),
            ("ИНН:", "inn"),
            ("КПП:", "kpp"),
            ("Индекс:", "postal_code"),
            ("Адрес:", "address"),
            ("Телефон:", "phone"),
            ("E-mail:", "email"),
            ("Реестр ФСА:", "fsa_registry_number"),
        )
        for r, (label, key) in enumerate(labels):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w", pady=5, padx=(0, 8))
            ttk.Entry(form, textvariable=fields[key]).grid(row=r, column=1, sticky="ew", pady=5)

        r = len(labels)
        ttk.Label(form, text="Тип:").grid(row=r, column=0, sticky="w", pady=5, padx=(0, 8))
        ttk.Combobox(
            form,
            textvariable=fields["org_type"],
            values=ORG_TYPE_VALUES,
            state="readonly",
            width=28,
        ).grid(row=r, column=1, sticky="w", pady=5)
        r += 1
        ttk.Checkbutton(form, text="Аккредитовано", variable=fields["is_accredited"]).grid(
            row=r, column=1, sticky="w", pady=5
        )

        def save() -> None:
            name = fields["name"].get().strip()
            if len(name) < 2:
                messagebox.showwarning("Организации", "Укажите название организации.")
                return
            ok = update_organization(
                int(row["id"]),
                name=name,
                address=fields["address"].get().strip() or None,
                postal_code=fields["postal_code"].get().strip() or None,
                phone=fields["phone"].get().strip() or None,
                email=fields["email"].get().strip() or None,
                inn=fields["inn"].get().strip() or None,
                kpp=fields["kpp"].get().strip() or None,
                is_accredited=fields["is_accredited"].get(),
                fsa_registry_number=fields["fsa_registry_number"].get().strip() or None,
                org_type=fields["org_type"].get(),
                db_path=self.db_path,
            )
            if not ok:
                messagebox.showerror("Организации", "Не удалось сохранить изменения.")
                return
            dialog.destroy()
            self._load_organizations()
            self.status.set(f"Организация обновлена: {name[:50]}")

        btns = ttk.Frame(dialog, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=save).pack(side="left")
        ttk.Button(btns, text="Отмена", command=dialog.destroy).pack(side="left", padx=8)

    def _browse_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите заявку",
            filetypes=[
                ("Заявки", "*.pdf;*.docx"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Все файлы", "*.*"),
            ],
        )
        if path:
            self.pdf_path_var.set(path)

    def _run_extract_pdf(self) -> None:
        doc_path = self.pdf_path_var.get().strip()
        if not doc_path:
            messagebox.showwarning("Заявка", "Выберите файл PDF или Word.")
            return

        self.status.set("Извлечение заявки…")

        def work() -> None:
            try:
                result = extract_from_document(
                    Path(doc_path),
                    use_ocr=self.ocr_var.get(),
                )
                out_dir = Path("data/extracted")
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"{Path(doc_path).stem}.json"
                out_file.write_text(
                    result.model_dump_json(indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                db_stats = {"saved": 0, "errors": 0}
                if self.save_marks_var.get() and result.cable_marks:
                    db_stats = save_cable_marks_from_matches(
                        result.cable_marks,
                        source=str(Path(doc_path).resolve()),
                        db_path=self.db_path,
                    )

                org_ids: dict[str, int | None] = {}
                if self.save_orgs_var.get() and result.organizations:
                    org_ids = save_organizations_from_extraction(
                        result.organizations,
                        source=str(Path(doc_path).resolve()),
                        db_path=self.db_path,
                    )
                extraction_id = save_document_extraction(
                    source_path=str(Path(doc_path).resolve()),
                    source_type=result.source_type,
                    text=result.text,
                    marks_count=len(result.cable_marks),
                    customer_org_id=org_ids.get("customer_org_id"),
                    manufacturer_org_id=org_ids.get("manufacturer_org_id"),
                    db_path=self.db_path,
                )
                self._last_document_extraction_id = extraction_id
                self._last_manufacturer_name = result.manufacturer_name or ""

                summary = [
                    f"Файл: {Path(doc_path).name}",
                    f"Тип: {result.source_type}",
                    f"Страниц: {result.page_count}",
                    f"Марок: {len(result.cable_marks)}",
                    f"OCR: {'да' if result.ocr_used else 'нет'}",
                    f"Марок в БД: {db_stats['saved']}",
                ]
                if result.customer_name:
                    summary.append(f"Заказчик: {result.customer_name}")
                if result.manufacturer_name and result.manufacturer_name != result.customer_name:
                    summary.append(f"Производитель: {result.manufacturer_name}")
                for org in result.organizations:
                    extras = []
                    if org.inn:
                        extras.append(f"ИНН {org.inn}")
                    if org.postal_code:
                        extras.append(org.postal_code)
                    if org.is_accredited:
                        extras.append("аккредитован")
                    if org.fsa_registry_number:
                        extras.append(org.fsa_registry_number)
                    suffix = f" ({', '.join(extras)})" if extras else ""
                    summary.append(f"  • [{org.role}] {org.name}{suffix}")
                summary.append(f"JSON: {out_file}")

                customer_name = result.customer_name

                def update_ui() -> None:
                    self.marks_list.delete(0, "end")
                    for m in result.cable_marks:
                        self.marks_list.insert("end", m.mark)
                    self._set_text(self.pdf_output, "\n".join(summary))
                    self._load_cable_marks()
                    if customer_name:
                        self.kp_customer_var.set(customer_name)
                    self._load_organizations()
                    self.parse_info_var.set(
                        self._format_parse_info(
                            file_name=Path(doc_path).name,
                            source_type=result.source_type,
                            marks_count=len(result.cable_marks),
                            customer_name=result.customer_name,
                            manufacturer_name=result.manufacturer_name,
                            ocr_used=result.ocr_used,
                            page_count=result.page_count,
                            extracted_at=result.extracted_at.isoformat(),
                        )
                    )
                    self.status.set("Заявка обработана")

                self.after(0, update_ui)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Ошибка извлечения", str(exc)))
                self.after(0, lambda: self.status.set("Ошибка"))

        threading.Thread(target=work, daemon=True).start()

    def _use_mark_in_calc(self) -> None:
        sel = self.marks_list.curselection()
        if not sel:
            return
        self.mark_var.set(self.marks_list.get(sel[0]))
        if self.notebook:
            self.notebook.select(self.tab_calc)
        self.status.set("Марка подставлена в расчёт")

    def _use_db_mark_in_calc(self) -> None:
        sel = self.cable_marks_tree.selection()
        if not sel:
            return
        self.mark_var.set(self.cable_marks_tree.item(sel[0], "values")[0])
        if self.notebook:
            self.notebook.select(self.tab_calc)
        self.status.set("Марка из БД подставлена в расчёт")

    def _load_kp_calculations(self) -> None:
        for item in self.kp_calc_tree.get_children():
            self.kp_calc_tree.delete(item)
        for row in get_calculations_for_kp(limit=100, db_path=self.db_path):
            self.kp_calc_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    row["mark"][:70],
                    f"{row['total_cost_without_vat']:.2f}",
                    f"{row['total_cost_with_vat']:.2f}",
                    row["created_at"][:16],
                ),
            )
        self._update_kp_preview()

    def _get_selected_kp_calc_ids(self) -> list[int]:
        return [int(iid) for iid in self.kp_calc_tree.selection()]

    def _select_all_kp_calcs(self) -> None:
        children = self.kp_calc_tree.get_children()
        if children:
            self.kp_calc_tree.selection_set(children)
            self._update_kp_preview()

    def _update_kp_preview(self) -> None:
        try:
            ids = self._get_selected_kp_calc_ids()
            if not ids:
                self.kp_preview_var.set("Выберите расчёты из списка (Ctrl+клик — несколько)")
                return
            rows = get_calculations_for_kp(ids, db_path=self.db_path)
            if not rows:
                self.kp_preview_var.set("Расчёты не найдены в БД")
                return
            proposal = proposal_from_calculations(
                customer=self.kp_customer_var.get(),
                subject=self.kp_subject_var.get(),
                calculations=rows,
            )
            self.kp_preview_var.set(
                f"Выбрано марок: {len(rows)}  |  "
                f"Итого без НДС: {format_money(proposal.total_without_vat)} ₽  |  "
                f"НДС: {format_money(proposal.total_vat)} ₽  |  "
                f"Итого с НДС: {format_money(proposal.total_with_vat)} ₽"
            )
        except Exception as exc:
            self.kp_preview_var.set(f"Ошибка превью: {exc}")

    def _run_generate_kp(self) -> None:
        ids = self._get_selected_kp_calc_ids()
        if not ids:
            messagebox.showwarning(
                "КП",
                "Выберите один или несколько расчётов в таблице ниже (Ctrl+клик).\n\n"
                "Если список пуст — сначала выполните расчёт на вкладке «2. Расчёт».",
            )
            return

        customer = self.kp_customer_var.get().strip()
        subject = self.kp_subject_var.get().strip()
        note = self.kp_note_text.get("1.0", "end").strip() or None

        safe_customer = re.sub(r'[<>:"/\\|?*«»]', "_", customer).strip("._ ")[:40] or "заказчик"
        out_dir = self.generated_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"КП_{safe_customer}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"

        self.status.set("Формирование КП…")
        self.update_idletasks()

        manufacturer = self._last_manufacturer_name.strip() or None
        doc_extraction_id = self._last_document_extraction_id

        def work() -> None:
            saved_path: Path | None = None
            order_id: int | None = None
            error: str | None = None
            try:
                saved_path = generate_kp_from_db(
                    customer=customer,
                    subject=subject,
                    calculation_ids=ids,
                    output_path=out_file,
                    db_path=self.db_path,
                    note=note,
                )
                order_id = create_order_from_kp(
                    customer_name=customer,
                    manufacturer_name=manufacturer,
                    subject=subject,
                    note=note,
                    calculation_ids=ids,
                    kp_output_path=str(saved_path),
                    document_extraction_id=doc_extraction_id,
                    db_path=self.db_path,
                )
            except Exception as exc:
                error = str(exc)

            def done() -> None:
                if error:
                    messagebox.showerror("Ошибка КП", error)
                    self.status.set("Ошибка формирования КП")
                    return
                assert saved_path is not None
                self.status.set(f"Заказ №{order_id} · КП: {saved_path.name}")
                self._load_orders_table()
                try:
                    import os

                    os.startfile(str(saved_path))
                except OSError:
                    pass
                messagebox.showinfo(
                    "Заказ оформлен",
                    f"Заказ №{order_id} сохранён.\n"
                    f"КП открыт в Word:\n{saved_path}",
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _load_orders_table(self) -> None:
        if not hasattr(self, "orders_tree"):
            return
        for item in self.orders_tree.get_children():
            self.orders_tree.delete(item)
        status_labels = {
            "kp_generated": "КП готов",
            "draft": "Черновик",
            "completed": "Завершён",
        }
        for row in list_orders(limit=200, db_path=self.db_path):
            status = status_labels.get(row.get("status") or "", row.get("status") or "")
            if row.get("application_path"):
                status = f"{status} · заявка" if status else "Заявка готова"
            self.orders_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    (row.get("created_at") or "")[:16].replace("T", " "),
                    (row.get("customer_name") or "—")[:40],
                    row.get("marks_count") or 0,
                    f"{float(row.get('total_with_vat') or 0):,.2f}".replace(",", " "),
                    status,
                ),
            )

    def _show_order_details(self) -> None:
        if not hasattr(self, "orders_tree"):
            return
        sel = self.orders_tree.selection()
        if not sel:
            return
        details = get_order_details(int(sel[0]), self.db_path)
        if not details:
            self._set_text(self.order_details, "Заказ не найден.")
            return
        lines = [
            f"Заказ №{details['id']}",
            f"Дата: {(details.get('created_at') or '')[:16].replace('T', ' ')}",
            f"Статус: {details.get('status', '')}",
            "",
            "ЗАКАЗЧИК",
            f"  {details.get('customer_name') or '—'}",
        ]
        if details.get("customer_inn"):
            lines.append(f"  ИНН: {details['customer_inn']}")
        if details.get("customer_address"):
            lines.append(f"  {details['customer_address']}")
        lines.extend(["", "ПРОИЗВОДИТЕЛЬ", f"  {details.get('manufacturer_name') or '—'}"])
        if details.get("manufacturer_inn"):
            lines.append(f"  ИНН: {details['manufacturer_inn']}")
        lines.extend([
            "",
            f"Предмет: {details.get('subject') or '—'}",
            f"Без НДС: {float(details.get('total_without_vat') or 0):,.2f} ₽".replace(",", " "),
            f"С НДС: {float(details.get('total_with_vat') or 0):,.2f} ₽".replace(",", " "),
        ])
        if details.get("source_document"):
            lines.append(f"\nЗаявка: {Path(details['source_document']).name}")
        if details.get("kp_output_path"):
            lines.append(f"КП: {details['kp_output_path']}")
        if details.get("application_path"):
            lines.append(f"Заявка на испытания: {details['application_path']}")
        apps = list_test_applications(order_id=int(sel[0]), limit=5, db_path=self.db_path)
        if apps:
            lines.append("\nИСТОРИЯ ЗАЯВОК (БД):")
            for app in apps:
                created = (app.get("created_at") or "")[:16].replace("T", " ")
                lines.append(
                    f"  • №{app.get('id')} от {created} — {app.get('test_type') or '—'}, "
                    f"марок: {app.get('marks_count') or 0}"
                )
                lines.append(f"    {app.get('output_path') or '—'}")
        if details.get("note"):
            lines.append(f"\nПримечание:\n{details['note']}")
        lines.append("\nМАРКИ:")
        for m in details.get("marks") or []:
            mfg = m.get("manufacturer_name") or details.get("manufacturer_name") or "—"
            lines.append(
                f"  • {m.get('mark')} — {float(m.get('total_with_vat') or 0):,.2f} ₽ "
                f"(производитель: {mfg})".replace(",", " ")
            )
        self._set_text(self.order_details, "\n".join(lines))

    def _get_selected_order_kp_path(self) -> Path | None:
        if not hasattr(self, "orders_tree"):
            return None
        sel = self.orders_tree.selection()
        if not sel:
            messagebox.showinfo("Заказы", "Выберите заказ в списке.")
            return None
        details = get_order_details(int(sel[0]), self.db_path)
        if not details or not details.get("kp_output_path"):
            messagebox.showwarning("Заказы", "Файл КП для этого заказа не найден.")
            return None
        path = Path(details["kp_output_path"])
        if not path.exists():
            messagebox.showwarning("Заказы", f"Файл не существует:\n{path}")
            return None
        return path

    def _open_selected_order_kp(self) -> None:
        path = self._get_selected_order_kp_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path))
            self.status.set(f"Открыт КП: {path.name}")
        except OSError as exc:
            messagebox.showerror("Заказы", str(exc))

    def _print_selected_order_kp(self) -> None:
        path = self._get_selected_order_kp_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path), "print")
            self.status.set(f"Печать: {path.name}")
        except OSError as exc:
            messagebox.showerror("Печать", f"Не удалось отправить на печать:\n{exc}")

    def _get_selected_order_id(self) -> int | None:
        if not hasattr(self, "orders_tree"):
            return None
        sel = self.orders_tree.selection()
        if not sel:
            messagebox.showinfo("Заказы", "Выберите заказ в списке.")
            return None
        return int(sel[0])

    def _get_selected_order_application_path(self) -> Path | None:
        order_id = self._get_selected_order_id()
        if order_id is None:
            return None
        details = get_order_details(order_id, self.db_path)
        if not details or not details.get("application_path"):
            messagebox.showwarning(
                "Заказы",
                "Заявка на испытания для этого заказа ещё не сформирована.\n"
                "Нажмите «Сформировать заявку».",
            )
            return None
        path = Path(details["application_path"])
        if not path.exists():
            messagebox.showwarning("Заказы", f"Файл не существует:\n{path}")
            return None
        return path

    def _generate_order_application(self) -> None:
        order_id = self._get_selected_order_id()
        if order_id is None:
            return

        self.status.set("Формирование заявки на испытания…")
        self.update_idletasks()

        def work() -> None:
            saved_path: Path | None = None
            error: str | None = None
            try:
                saved_path = generate_application_from_order(
                    order_id,
                    db_path=self.db_path,
                )
            except Exception as exc:
                error = str(exc)

            def done() -> None:
                if error:
                    self.status.set("Ошибка формирования заявки")
                    messagebox.showerror("Заявка на испытания", error)
                    return
                assert saved_path is not None
                self.status.set(f"Заказ №{order_id} · заявка: {saved_path.name}")
                self._load_orders_table()
                self._show_order_details()
                try:
                    import os

                    os.startfile(str(saved_path))
                except OSError:
                    pass
                messagebox.showinfo(
                    "Заявка сформирована",
                    f"Заявка на испытания сохранена:\n{saved_path}",
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _open_selected_order_application(self) -> None:
        path = self._get_selected_order_application_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path))
            self.status.set(f"Открыта заявка: {path.name}")
        except OSError as exc:
            messagebox.showerror("Заказы", str(exc))

    def _print_selected_order_application(self) -> None:
        path = self._get_selected_order_application_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path), "print")
            self.status.set(f"Печать заявки: {path.name}")
        except OSError as exc:
            messagebox.showerror("Печать", f"Не удалось отправить на печать:\n{exc}")

    def _load_history(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for row in get_recent_calculations(50, self.db_path):
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["created_at"][:16],
                    row["mark"][:80],
                    f"{row['total_cost_with_vat']:.2f}",
                    row["source"],
                ),
            )

    def _load_tests(self) -> None:
        for item in self.tests_tree.get_children():
            self.tests_tree.delete(item)
        self._tests_by_code.clear()

        search = (getattr(self, "tests_search_var", None) or tk.StringVar()).get().strip().lower()
        rows = list_test_items(limit=500, db_path=self.db_path)

        by_category: dict[str, list[dict]] = {}
        for row in rows:
            if search and search not in row["name"].lower() and search not in row["code"].lower():
                cat = (row.get("category") or "").lower()
                if search not in cat:
                    continue
            cat = (row.get("category") or "Без категории").strip()
            by_category.setdefault(cat, []).append(row)

        for cat in sorted(by_category.keys(), key=category_sort_key):
            tests = sorted(by_category[cat], key=lambda r: r["name"])
            short = CATEGORY_SHORT.get(cat, cat[:14])
            cat_iid = f"cat::{cat}"
            cat_tag = self._category_tags.get(cat, "category")
            count = len(tests)
            self.tests_tree.insert(
                "",
                "end",
                iid=cat_iid,
                text=f"  {cat}  ({count})",
                values=("", "", ""),
                tags=("category", cat_tag),
                open=True,
            )
            for row in tests:
                rule_params = json.loads(row.get("rule_params") or "{}")
                default_h = rule_params.get("default_hours", "")
                if row["rule_type"] != "time_based":
                    default_h = ""
                self._tests_by_code[row["code"]] = row
                tags: tuple[str, ...] = ()
                if is_climatic_code(row["code"]):
                    tags = ("climatic",)
                self.tests_tree.insert(
                    cat_iid,
                    "end",
                    iid=f"test::{row['code']}",
                    text=f"    {row['name']}",
                    values=(
                        f"{row['base_cost']:.0f}",
                        rule_type_label(row["rule_type"]),
                        default_h,
                    ),
                    tags=tags,
                )

    def _load_cable_marks(self) -> None:
        for item in self.cable_marks_tree.get_children():
            self.cable_marks_tree.delete(item)
        search = self.marks_search_var.get().strip() or None
        for row in list_cable_marks(search=search, limit=500, db_path=self.db_path):
            unit = "мм²" if row.get("size_unit") == "mm2" else "мм"
            self.cable_marks_tree.insert(
                "",
                "end",
                values=(
                    row["full_mark"],
                    row["brand"],
                    row.get("fire_class") or "",
                    row["cores_count"],
                    row.get("structural_element_type") or "",
                    f"{row['characteristic_size']} {unit}",
                    (row.get("document") or "")[:50],
                ),
            )

    def _load_settings(self) -> None:
        settings = get_climatic_settings(self.db_path) or ClimaticTestSettings()
        for key, var in self.setting_vars.items():
            var.set(str(getattr(settings, key)))

    def _save_settings(self) -> None:
        try:
            settings = ClimaticTestSettings(
                **{
                    key: float(var.get().replace(",", "."))
                    for key, var in self.setting_vars.items()
                }
            )
        except ValueError:
            messagebox.showerror("Настройки", "Укажите корректные числа часов.")
            return
        save_climatic_settings(settings, self.db_path)
        self.status.set("Настройки выдержки сохранены")

    def _add_test_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Новое испытание")
        dialog.geometry("500x380")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()

        fields: dict[str, tk.Variable] = {
            "code": tk.StringVar(),
            "name": tk.StringVar(),
            "base_cost": tk.StringVar(value="100"),
            "category": tk.StringVar(value="Внешние воздействующие факторы"),
            "rule_type": tk.StringVar(value="fixed"),
            "default_hours": tk.StringVar(value="2"),
            "hours_key": tk.StringVar(),
            "cost_per_hour": tk.StringVar(value="0"),
        }

        row = 0
        for label, key in (
            ("Код (slug):", "code"),
            ("Наименование:", "name"),
            ("Базовая цена:", "base_cost"),
            ("Категория:", "category"),
        ):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=5)
            ttk.Entry(dialog, textvariable=fields[key], width=42).grid(
                row=row, column=1, sticky="ew", padx=12, pady=5
            )
            row += 1

        ttk.Label(dialog, text="Правило:").grid(row=row, column=0, sticky="w", padx=12, pady=5)
        ttk.Combobox(
            dialog,
            textvariable=fields["rule_type"],
            values=["fixed", "per_core", "per_group", "time_based"],
            state="readonly",
            width=18,
        ).grid(row=row, column=1, sticky="w", padx=12, pady=5)
        row += 1

        for label, key in (("Ключ часов:", "hours_key"), ("Часы:", "default_hours"), ("Цена/час:", "cost_per_hour")):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=12, pady=5)
            ttk.Entry(dialog, textvariable=fields[key], width=42).grid(
                row=row, column=1, sticky="ew", padx=12, pady=5
            )
            row += 1

        def save() -> None:
            code = fields["code"].get().strip()
            if not code:
                messagebox.showwarning("Испытание", "Укажите код.", parent=dialog)
                return
            rule_params: dict = {}
            if fields["rule_type"].get() == "time_based":
                rule_params = {
                    "hours_key": fields["hours_key"].get().strip() or code,
                    "default_hours": float(fields["default_hours"].get()),
                    "cost_per_hour": float(fields["cost_per_hour"].get()),
                }
            try:
                item = TestItemCreate(
                    code=code,
                    name=fields["name"].get().strip() or code,
                    base_cost=float(fields["base_cost"].get()),
                    category=fields["category"].get().strip(),
                    rule_type=fields["rule_type"].get(),  # type: ignore[arg-type]
                    rule_params=rule_params,
                )
                add_test_item(item, self.db_path)
            except Exception as exc:
                messagebox.showerror("Ошибка", str(exc), parent=dialog)
                return
            dialog.destroy()
            self._load_tests()
            self.status.set(f"Испытание {code} добавлено")

        ttk.Button(dialog, text="Сохранить", style="Accent.TButton", command=save).grid(
            row=row, column=0, columnspan=2, pady=14
        )
        dialog.columnconfigure(1, weight=1)


def main() -> None:
    app = RequestProcessorApp()
    app.mainloop()


if __name__ == "__main__":
    main()