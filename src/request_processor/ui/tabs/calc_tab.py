"""Mixin: CalcTabMixin — domain methods for Lab_request GUI."""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from ...calculation.climatic_tests import climatic_settings_fields, is_climatic_code
from ...calculation.test_rules import (
    CATEGORY_COLORS,
    CATEGORY_SHORT,
    category_sort_key,
    rule_type_label,
)
from ...logging_setup import get_logger
from ...parsing.cable_mark_parser import parse_cable_mark_record
from ...calculation.cost_calculator import calculate_cost, format_breakdown
from ...validation.extraction_validator import apply_operator_edits, validate_extraction
from ...mapping.requirement_mapper import map_requirements_to_tests
from ...models import (
    AssistantLlmSettings,
    DocumentPackSettings,
    CableMarkMatch,
    ClimaticTestSettings,
    FieldStatus,
    MarkValidation,
    PdfExtractionResult,
    TestItemCreate,
    ValidationReport,
)
from ...extraction.test_type_extractor import (
    TEST_TYPE_OPTIONS,
    build_kp_subject,
    detect_test_type,
    format_test_type_label,
)
from ...assistant.feedback import AssistantFeedbackEvent, append_assistant_feedback
from ...assistant.models import AssistantContext
from ...extraction.pdf_extractor import (
    DEFAULT_OCR_DPI,
    EASYOCR_OCR_DPI,
    SCAN_OCR_DPI,
)
from ..theme import (
    COLORS,
    apply_fluent_theme,
    enable_windows_dpi_awareness,
    fit_window_to_screen,
    make_primary_button,
    make_secondary_button,
)
from ..state import ORG_TYPE_LABELS, ORG_TYPE_VALUES, CalcTestEntry, ExtractionDraft
from ...generation.kp_generator import format_money, generate_kp_from_db, proposal_from_calculations
from ...persistence.sqlite_repo import (
    DB_PATH_DEFAULT,
    GENERATED_DIR_DEFAULT,
    add_test_item,
    build_default_hours_map,
    get_calculations_for_kp,
    get_assistant_llm_settings,
    get_climatic_settings,
    get_document_pack_settings,
    get_last_document_extraction,
    get_organization_by_id,
    get_recent_calculations,
    init_db,
    list_cable_marks,
    list_organizations,
    list_test_items,
    save_calculation,
    save_cable_marks_from_matches,
    save_cable_marks_from_validations,
    save_assistant_llm_settings,
    save_climatic_settings,
    save_document_pack_settings,
    push_recent_pack_path,
    save_document_extraction,
    save_organizations_from_extraction,
    update_organization,
    create_order_from_kp,
    list_orders,
    get_order_details,
    list_test_applications,
    list_test_mappings,
    add_test_mapping,
    update_test_mapping,
    delete_test_mapping,
    delete_cable_mark,
    delete_calculation,
    delete_order,
    delete_organization,
    delete_generated_document,
    record_mapping_usage,
    list_test_programs,
    get_test_program,
    delete_test_program,
)

_log = get_logger("ui.gui")

class CalcTabMixin:
    def _build_calc_tab(self) -> None:
        btns = ttk.Frame(self.tab_calc)
        btns.pack(side="bottom", fill="x", pady=(8, 0))
        self._accent_button(btns, "Рассчитать", self._run_calculate).pack(side="left")
        ttk.Button(btns, text="Очистить всё", command=self._clear_calc).pack(side="left", padx=10)
        ttk.Label(
            btns,
            text="Климатические испытания — укажите часы выдержки в списке слева",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

        top = ttk.LabelFrame(self.tab_calc, text="Марка кабеля", padding=12, style="Card.TLabelframe")
        top.pack(fill="x", pady=(0, 10))
        top.configure(style="Card.TLabelframe")

        inner = ttk.Frame(top, style="Card.TFrame")
        inner.pack(fill="x")
        # master=self: на Py 3.14 StringVar без master иногда «не цепляется» к Entry
        self.mark_var = tk.StringVar(master=self)
        mark_row = ttk.Frame(inner, style="Card.TFrame")
        mark_row.pack(fill="x")
        self.calc_mark_entry = ttk.Entry(
            mark_row, textvariable=self.mark_var, font=("Segoe UI", 11)
        )
        self.calc_mark_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._secondary_button(
            mark_row,
            "Испытания из заявки",
            self._apply_suggested_tests_from_application,
        ).pack(side="left", padx=(8, 0))
        self._accent_button(mark_row, "Рассчитать", self._run_calculate).pack(side="left", padx=(8, 0))
        self.calc_suggestions_var = tk.StringVar(value="")
        ttk.Label(
            inner,
            textvariable=self.calc_suggestions_var,
            style="CardMuted.TLabel",
            wraplength=720,
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(
            inner,
            text="С вкладки «1. Заявка»: выберите марку → «→ В расчёт» или двойной клик по строке",
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        ttk.Label(
            inner,
            text="Пример: ВВГ-Пнг(А) 3х4ок(М,РЕ)-0,66",
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self.mark_var.trace_add(
            "write",
            lambda *_: (
                self._update_calc_suggestions_hint(),
                self._show_calc_picker_mode(),
                self._refresh_calc_picker(),
            ),
        )

        opts = ttk.Frame(top, style="Card.TFrame")
        opts.pack(fill="x", pady=(8, 0))
        self.calc_armor_var = tk.BooleanVar(value=False)
        armor_cb = ttk.Checkbutton(
            opts,
            text="Бронированный кабель (+0.5 к сложности образца)",
            variable=self.calc_armor_var,
            style="Card.TCheckbutton",
            takefocus=False,
        )
        armor_cb.pack(side="left")
        ttk.Label(opts, text="Скидка, %", style="CardMuted.TLabel").pack(side="left", padx=(16, 4))
        self.calc_discount_var = tk.StringVar(value="0")
        ttk.Spinbox(
            opts,
            textvariable=self.calc_discount_var,
            from_=0,
            to=100,
            increment=1,
            width=5,
        ).pack(side="left")
        ttk.Label(opts, text="Наценка, %", style="CardMuted.TLabel").pack(side="left", padx=(12, 4))
        self.calc_markup_var = tk.StringVar(value="0")
        ttk.Spinbox(
            opts,
            textvariable=self.calc_markup_var,
            from_=0,
            to=100,
            increment=1,
            width=5,
        ).pack(side="left")

        mid = ttk.PanedWindow(self.tab_calc, orient="horizontal")
        mid.pack(fill="both", expand=True)

        left = ttk.LabelFrame(mid, text="Выбранные испытания", padding=8, style="Card.TLabelframe")
        mid.add(left, weight=1)

        list_header = ttk.Frame(left, style="Card.TFrame")
        list_header.pack(fill="x", pady=(0, 6))
        ttk.Label(list_header, text="Испытание", style="Card.TLabel", width=30).pack(side="left")
        ttk.Label(list_header, text="Правило", style="Card.TLabel", width=10).pack(side="left")
        ttk.Label(list_header, text="Кол-во", style="Card.TLabel", width=6).pack(side="left")
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
        self._calc_canvas_window = self._calc_canvas.create_window(
            (0, 0), window=self.calc_tests_inner, anchor="nw"
        )

        def _on_calc_inner_configure(_event=None) -> None:
            try:
                self._calc_canvas.configure(scrollregion=self._calc_canvas.bbox("all"))
            except tk.TclError:
                pass

        def _on_calc_canvas_configure(event: tk.Event) -> None:
            # Без ширины inner=1px — строки «есть», но слева пусто.
            try:
                self._calc_canvas.itemconfigure(self._calc_canvas_window, width=max(event.width, 1))
            except tk.TclError:
                pass

        self.calc_tests_inner.bind("<Configure>", _on_calc_inner_configure)
        self._calc_canvas.bind("<Configure>", _on_calc_canvas_configure)
        self._calc_canvas.configure(yscrollcommand=calc_scroll.set)
        self._calc_canvas.pack(side="left", fill="both", expand=True)
        calc_scroll.pack(side="right", fill="y")
        from ..widgets.mousewheel import register_canvas_mousewheel

        register_canvas_mousewheel(canvas_frame, self._calc_canvas, priority=40)

        self._calc_empty_label = ttk.Label(
            self.calc_tests_inner,
            text="Отметьте испытания справа\nили «Из заявки →»",
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

        self.calc_right_panel = ttk.LabelFrame(
            mid, text="Испытания для расчёта", padding=8, style="Card.TLabelframe"
        )
        mid.add(self.calc_right_panel, weight=2)

        self.calc_picker_frame = ttk.Frame(self.calc_right_panel, style="Card.TFrame")

        # --- toolbar: поиск + категория + режимы + bulk ---
        picker_toolbar = ttk.Frame(self.calc_picker_frame, style="Card.TFrame")
        picker_toolbar.pack(fill="x", pady=(0, 4))

        search_row = ttk.Frame(picker_toolbar, style="Card.TFrame")
        search_row.pack(fill="x")
        ttk.Label(search_row, text="Поиск:", style="Card.TLabel").pack(side="left")
        self.calc_picker_search_var = tk.StringVar(value="")
        search_entry = ttk.Entry(search_row, textvariable=self.calc_picker_search_var, width=28)
        search_entry.pack(side="left", padx=(4, 8), fill="x", expand=True)
        # debounce поиска: не перестраивать 60+ строк на каждый символ
        self._calc_picker_search_after: str | None = None
        self.calc_picker_search_var.trace_add("write", lambda *_: self._on_picker_search_typed())

        ttk.Label(search_row, text="Категория:", style="Card.TLabel").pack(side="left")
        # Источник истины фильтра — _picker_active_category (НЕ StringVar combobox).
        # Windows ttk.Combobox после configure(values=…) часто сбрасывает var/display
        # в «Все», а на экране ещё секунду видна старая категория → «показано 61/61».
        self._picker_active_category: str = "Все"
        self._picker_category_ui_lock: bool = False
        # textvariable оставляем для smoke-тестов и чтения, но фильтр его не слушает
        self.calc_picker_category_var = tk.StringVar(value="Все")
        self.calc_picker_category_combo = ttk.Combobox(
            search_row,
            textvariable=self.calc_picker_category_var,
            values=["Все"],
            state="readonly",
            width=34,
        )
        self.calc_picker_category_combo.pack(side="left", padx=(4, 0))
        # Только явный выбор пользователя. Не trace на var и не FocusOut:
        # configure(values)/сброс display в «Все» иначе затирает active-кэш.
        self.calc_picker_category_combo.bind(
            "<<ComboboxSelected>>", self._on_picker_category_selected
        )
        self.calc_picker_category_combo.bind(
            "<Return>", self._on_picker_category_selected
        )

        bulk_row = ttk.Frame(picker_toolbar, style="Card.TFrame")
        bulk_row.pack(fill="x", pady=(4, 0))
        ttk.Button(
            bulk_row,
            text="Из заявки →",
            command=self._picker_select_suggested,
        ).pack(side="left")
        ttk.Button(
            bulk_row,
            text="Отметить видимые",
            command=self._picker_select_visible,
        ).pack(side="left", padx=4)
        ttk.Button(
            bulk_row,
            text="Снять видимые",
            command=self._picker_clear_visible,
        ).pack(side="left")
        self.calc_picker_stats_var = tk.StringVar(value="")
        ttk.Label(
            bulk_row,
            textvariable=self.calc_picker_stats_var,
            style="CardMuted.TLabel",
        ).pack(side="right")

        # режим radio убран: «Из заявки»/«Выбранные» без данных обнуляли список
        # (выглядело как баг). Всегда полный прайс; подсказки — ★ и кнопка «Из заявки →».
        self.calc_picker_mode_var = tk.StringVar(value="all")

        ttk.Label(
            self.calc_picker_frame,
            text="Полный прайс. ★ — из заявки. Галочка → слева. "
            "«Из заявки →» отметит подсказки. Климатика — часы слева.",
            style="CardMuted.TLabel",
            wraplength=480,
        ).pack(anchor="w", pady=(0, 4))

        picker_list_frame = ttk.Frame(self.calc_picker_frame, style="Card.TFrame")
        picker_list_frame.pack(fill="both", expand=True)
        self.calc_picker_list_stats_var = tk.StringVar(value="")
        ttk.Label(
            picker_list_frame,
            textvariable=self.calc_picker_list_stats_var,
            style="CardMuted.TLabel",
        ).pack(anchor="w", pady=(0, 4))

        # Canvas + ttk.Checkbutton (не Treeview): create_window один раз;
        # refresh уничтожает только строки, BooleanVar стабильны между фильтрами.
        self._calc_picker_canvas_frame = ttk.Frame(picker_list_frame, style="Card.TFrame")
        self._calc_picker_canvas_frame.pack(fill="both", expand=True)
        self._calc_picker_canvas = tk.Canvas(
            self._calc_picker_canvas_frame,
            bg=COLORS["card"],
            highlightthickness=0,
            borderwidth=0,
        )
        picker_scroll = ttk.Scrollbar(
            self._calc_picker_canvas_frame,
            orient="vertical",
            command=self._calc_picker_canvas.yview,
        )
        self.calc_picker_inner = ttk.Frame(self._calc_picker_canvas, style="Card.TFrame")
        self._calc_picker_canvas_window = self._calc_picker_canvas.create_window(
            (0, 0),
            window=self.calc_picker_inner,
            anchor="nw",
        )
        self.calc_picker_inner.bind(
            "<Configure>",
            lambda _e: self._schedule_picker_geometry(),
        )
        self._calc_picker_canvas.bind(
            "<Configure>",
            lambda e: self._calc_picker_canvas.itemconfigure(
                self._calc_picker_canvas_window,
                width=max(int(e.width), 1),
            ),
        )
        self._calc_picker_canvas.configure(yscrollcommand=picker_scroll.set)
        self._calc_picker_canvas.pack(side="left", fill="both", expand=True)
        picker_scroll.pack(side="right", fill="y")
        from ..widgets.mousewheel import register_canvas_mousewheel as _reg_picker_wheel

        _reg_picker_wheel(
            self._calc_picker_canvas_frame,
            self._calc_picker_canvas,
            priority=40,
        )
        self._calc_picker_checkbuttons: dict[str, ttk.Checkbutton] = {}
        self._calc_picker_geometry_after: str | None = None

        self.calc_picker_empty_var = tk.StringVar(
            value="Укажите марку — появятся испытания из заявки или полный справочник."
        )
        self._calc_picker_empty_label = ttk.Label(
            picker_list_frame,
            textvariable=self.calc_picker_empty_var,
            style="CardMuted.TLabel",
            wraplength=400,
            justify="left",
        )
        self._calc_picker_visible_codes: list[str] = []

        self.calc_result_frame = ttk.Frame(self.calc_right_panel, style="Card.TFrame")
        self.calc_result_btns = ttk.Frame(self.calc_result_frame, style="Card.TFrame")
        ttk.Button(
            self.calc_result_btns,
            text="← К выбору испытаний",
            command=self._show_calc_picker_mode,
        ).pack(anchor="w", pady=(0, 6))
        self.calc_output = self._make_readonly_text(
            self.calc_result_frame,
            height=14,
            font=("Consolas", 10),
            bg="#f8fafc",
            fg=COLORS["text"],
            relief="flat",
            padx=8,
            pady=8,
        )
        self.calc_output.pack(fill="both", expand=True)

        self._show_calc_picker_mode()

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

    def _find_calc_entry(self, code: str) -> CalcTestEntry | None:
        for entry in self._calc_entries:
            if entry.code == code:
                return entry
        return None

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
            text=entry.name[:36],
            style="Card.TLabel",
            width=30,
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

        qty_frame = ttk.Frame(inner, style=bg_style)
        qty_frame.pack(side="left", padx=(4, 0))
        if entry.quantity_var is not None:
            ttk.Spinbox(
                qty_frame,
                textvariable=entry.quantity_var,
                from_=1,
                to=999,
                increment=1,
                width=4,
                font=("Segoe UI", 10),
            ).pack(side="left")
        else:
            ttk.Label(qty_frame, text="1", style="CardMuted.TLabel", width=4).pack(side="left")

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
        self._sync_picker_var(entry.code, False)
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
        self._refresh_calc_picker()

    def _update_calc_count_label(self) -> None:
        if hasattr(self, "calc_count_var"):
            self.calc_count_var.set(f"В расчёте: {len(self._calc_entries)}")

    def _on_test_double_click(self, event: tk.Event) -> None:
        item = self.tests_tree.identify_row(event.y)
        if not item or not str(item).startswith("test::"):
            return
        code = str(item).removeprefix("test::")
        self._add_test_to_calc(code)

    def _build_hours_map(self) -> dict[str, float]:
        hours = build_default_hours_map(self.db_path)
        for entry in self._calc_entries:
            if entry.rule_type == "time_based" and entry.hours_var and entry.hours_key:
                try:
                    hours[entry.hours_key] = float(entry.hours_var.get().replace(",", "."))
                except ValueError:
                    pass
        return hours

    def _build_quantities_map(self) -> dict[str, int]:
        quantities: dict[str, int] = {}
        for entry in self._calc_entries:
            if entry.quantity_var is None:
                quantities[entry.code] = 1
                continue
            try:
                quantities[entry.code] = max(1, int(entry.quantity_var.get()))
            except ValueError:
                quantities[entry.code] = 1
        return quantities

    def _update_calc_suggestions_hint(self) -> None:
        mark = self.mark_var.get().strip()
        codes = self._suggested_test_codes_for_mark(mark)
        if codes:
            self.calc_suggestions_var.set(
                f"Из заявки для этой марки: {', '.join(codes)} — отметьте справа или «Испытания из заявки»"
            )
        else:
            self.calc_suggestions_var.set(
                "Подсказок из заявки нет — отметьте испытания справа или добавьте из справочника."
                if mark
                else ""
            )

    def _show_calc_picker_mode(self) -> None:
        if not hasattr(self, "calc_picker_frame"):
            return
        if hasattr(self, "calc_result_frame"):
            self.calc_result_frame.pack_forget()
        self.calc_picker_frame.pack(fill="both", expand=True)
        self.calc_right_panel.configure(text="Испытания для расчёта")
        self._refresh_calc_picker()

    def _show_calc_result_mode(self, text: str) -> None:
        if not hasattr(self, "calc_picker_frame"):
            return
        self.calc_picker_frame.pack_forget()
        if hasattr(self, "calc_result_btns"):
            self.calc_result_btns.pack(fill="x", anchor="w")
        if hasattr(self, "calc_result_frame"):
            self.calc_result_frame.pack(fill="both", expand=True)
        self.calc_right_panel.configure(text="Результат расчёта")
        self._set_text(self.calc_output, text)

    def _on_picker_search_typed(self) -> None:
        """Поиск с короткой задержкой — иначе UI «мигает» на каждый символ."""
        after_id = getattr(self, "_calc_picker_search_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except (tk.TclError, ValueError):
                pass
        self._calc_picker_search_after = self.after(180, self._refresh_calc_picker)

    def _picker_all_catalog_codes(self) -> list[str]:
        """Полный справочник, отсортированный по категории и имени."""
        if not self._tests_by_code:
            return []
        return sorted(
            self._tests_by_code.keys(),
            key=lambda c: (
                category_sort_key(self._tests_by_code[c].get("category")),
                (self._tests_by_code[c].get("name") or c).lower(),
            ),
        )

    def _picker_candidate_codes(self, mark: str) -> list[str]:
        """Базовый набор кодов (до фильтра поиска/режима)."""
        suggested = self._suggested_test_codes_for_mark(mark) if mark else []
        selected = [e.code for e in self._calc_entries]
        catalog = self._picker_all_catalog_codes()
        # Всегда полный справочник + выбранные (если прайс ещё не загружен)
        if catalog:
            return catalog
        return list(dict.fromkeys(suggested + selected))

    def _read_picker_category_ui(self) -> str:
        """Считать выбранную категорию после завершения native combobox event."""
        combo = getattr(self, "calc_picker_category_combo", None)
        if combo is not None:
            try:
                index = int(combo.current())
                raw_values = combo.cget("values") or ()
                values = (
                    list(self.tk.splitlist(raw_values))
                    if isinstance(raw_values, str)
                    else list(raw_values)
                )
                if 0 <= index < len(values):
                    return str(values[index]).strip()
            except (tk.TclError, TypeError, ValueError):
                pass

        raw = ""
        if hasattr(self, "calc_picker_category_var"):
            raw = (self.calc_picker_category_var.get() or "").strip()
        if not raw and combo is not None:
            try:
                raw = (combo.get() or "").strip()
            except tk.TclError:
                raw = ""
        return raw

    def _on_picker_category_selected(self, _event: object | None = None) -> None:
        """Пользователь выбрал категорию; mouse event применяем после native update."""
        if getattr(self, "_picker_category_ui_lock", False):
            return
        if _event is not None:
            after_id = getattr(self, "_picker_category_after", None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except (tk.TclError, ValueError):
                    pass
            self._picker_category_after = self.after_idle(
                self._apply_picker_category_selection
            )
            return
        self._apply_picker_category_selection()

    def _apply_picker_category_selection(self) -> None:
        """Зафиксировать уже установленное native-значение combobox и обновить список."""
        self._picker_category_after = None
        if getattr(self, "_picker_category_ui_lock", False):
            return
        raw = self._read_picker_category_ui()
        combo = getattr(self, "calc_picker_category_combo", None)
        current = -1
        try:
            if combo is not None:
                current = int(combo.current())
        except (tk.TclError, TypeError, ValueError):
            current = -1
        _log.debug(
            "picker category event: active=%r raw=%r var=%r combo=%r current=%r lock=%r",
            getattr(self, "_picker_active_category", None),
            raw,
            (self.calc_picker_category_var.get() if hasattr(self, "calc_picker_category_var") else None),
            (combo.get() if combo is not None else None),
            current,
            getattr(self, "_picker_category_ui_lock", False),
        )
        if not raw:
            return
        normalized = self._normalize_picker_category(raw)
        self._picker_active_category = normalized
        self._sync_picker_category_display(normalized)
        self._refresh_calc_picker()

    def _sync_picker_category_display(self, category: str) -> None:
        """Показать category в combobox, не трогая _picker_active_category."""
        if not hasattr(self, "calc_picker_category_combo"):
            return
        self._picker_category_ui_lock = True
        try:
            if hasattr(self, "calc_picker_category_var"):
                if (self.calc_picker_category_var.get() or "").strip() != category:
                    self.calc_picker_category_var.set(category)
            try:
                if (self.calc_picker_category_combo.get() or "").strip() != category:
                    self.calc_picker_category_combo.set(category)
            except tk.TclError:
                pass
        finally:
            self._picker_category_ui_lock = False

    def _normalize_picker_category(self, raw: str) -> str:
        """Привести значение combobox к полной категории прайса или «Все»."""
        text = (raw or "").strip()
        if not text or text.casefold() in ("все", "all", "*"):
            return "Все"
        known = {
            (t.get("category") or "Без категории").strip()
            for t in self._tests_by_code.values()
        }
        if text in known:
            return text
        # короткое имя из CATEGORY_SHORT → полное
        for full, short in CATEGORY_SHORT.items():
            if text == short or text.casefold() == short.casefold():
                if full in known or not known:
                    return full
        # prefix / contains (combobox мог обрезать длинное имя)
        text_cf = text.casefold()
        for full in known:
            if full.casefold() == text_cf or full.casefold().startswith(text_cf):
                return full
        for full in known:
            if text_cf in full.casefold():
                return full
        # неизвестная строка — не фильтровать «в никуда»
        if known:
            return "Все"
        return text

    def _picker_category_filter(self) -> str:
        """Категория для фильтра: только _picker_active_category (не combobox var)."""
        raw = getattr(self, "_picker_active_category", None) or "Все"
        return self._normalize_picker_category(raw)

    def _picker_filtered_codes(self, mark: str) -> list[str]:
        """Коды с учётом категории и поиска (всегда полный прайс, без radio-режимов)."""
        search_var = getattr(self, "calc_picker_search_var", None)
        search = (search_var.get() if search_var is not None else "").strip().lower()

        cat_filter = self._picker_category_filter()

        selected = {e.code for e in self._calc_entries}
        codes = self._picker_candidate_codes(mark)

        filtered: list[str] = []
        for code in codes:
            test = self._tests_by_code.get(code)
            if not test and code not in selected:
                continue
            cat = ((test or {}).get("category") or "Без категории").strip()
            if cat_filter != "Все" and cat != cat_filter:
                continue
            if search:
                name = ((test or {}).get("name") or "").lower()
                blob = f"{code} {name} {cat}".lower()
                if search not in blob:
                    continue
            filtered.append(code)
        return filtered

    def _update_picker_category_combo(self) -> None:
        """Обновить values combobox; display ← active (var не источник фильтра)."""
        if not hasattr(self, "calc_picker_category_combo"):
            return
        cats = sorted(
            {
                (t.get("category") or "Без категории").strip()
                for t in self._tests_by_code.values()
            },
            key=category_sort_key,
        )
        values = ["Все"] + cats
        raw_prev = self.calc_picker_category_combo.cget("values") or ()
        # ttk на Windows иногда отдаёт str — нормализуем к list[str]
        if isinstance(raw_prev, str):
            prev = list(self.tk.splitlist(raw_prev)) if raw_prev else []
        else:
            prev = list(raw_prev)

        # active — единственный источник; сброс только если категории больше нет в прайсе
        desired = getattr(self, "_picker_active_category", None) or "Все"
        desired = self._normalize_picker_category(desired)
        if desired != "Все" and desired not in values:
            desired = "Все"
        self._picker_active_category = desired

        self._picker_category_ui_lock = True
        try:
            if prev != values:
                self.calc_picker_category_combo.configure(values=values)
            # всегда восстанавливаем display из active (Windows мог сбросить в «Все»)
            self.calc_picker_category_var.set(desired)
            try:
                self.calc_picker_category_combo.set(desired)
            except tk.TclError:
                pass
        finally:
            self._picker_category_ui_lock = False

    def _get_picker_var(self, code: str) -> tk.BooleanVar:
        """Стабильный BooleanVar: не пересоздаётся при смене фильтра/поиска."""
        var = self._calc_picker_vars.get(code)
        if var is None:
            var = tk.BooleanVar(master=self, value=False)
            self._calc_picker_vars[code] = var
        return var

    def _sync_picker_var(self, code: str, checked: bool) -> None:
        var = self._get_picker_var(code)
        self._calc_picker_syncing = True
        try:
            var.set(checked)
        finally:
            self._calc_picker_syncing = False

    def _schedule_picker_geometry(self) -> None:
        """Схлопнуть несколько Configure в один after_idle geometry pass."""
        after_id = getattr(self, "_calc_picker_geometry_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except (tk.TclError, ValueError):
                pass
        self._calc_picker_geometry_after = self.after_idle(self._finish_picker_geometry)

    def _finish_picker_geometry(self) -> None:
        self._calc_picker_geometry_after = None
        canvas = getattr(self, "_calc_picker_canvas", None)
        inner = getattr(self, "calc_picker_inner", None)
        if canvas is None or inner is None:
            return
        try:
            canvas.update_idletasks()
            win = getattr(self, "_calc_picker_canvas_window", None)
            if win is not None:
                width = max(int(canvas.winfo_width()), 1)
                canvas.itemconfigure(win, width=width)
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)
            _log.debug(
                "picker geometry: visible_rows=%d inner_children=%d "
                "canvas=%sx%s inner=%sx%s bbox=%r scrollregion=%r",
                len(getattr(self, "_calc_picker_visible_codes", []) or []),
                len(inner.winfo_children()),
                canvas.winfo_width(),
                canvas.winfo_height(),
                inner.winfo_width(),
                inner.winfo_height(),
                bbox,
                canvas.cget("scrollregion"),
            )
        except tk.TclError:
            pass

    def _show_picker_empty(self, message: str) -> None:
        canvas_frame = getattr(self, "_calc_picker_canvas_frame", None)
        if canvas_frame is not None and canvas_frame.winfo_manager() == "pack":
            canvas_frame.pack_forget()
        self._calc_picker_empty_label.pack(anchor="w", pady=8)
        self.calc_picker_empty_var.set(message)

    def _show_picker_list(self) -> None:
        if self._calc_picker_empty_label.winfo_manager() == "pack":
            self._calc_picker_empty_label.pack_forget()
        canvas_frame = getattr(self, "_calc_picker_canvas_frame", None)
        if canvas_frame is not None and canvas_frame.winfo_manager() != "pack":
            canvas_frame.pack(fill="both", expand=True)

    def _clear_picker_rows(self) -> None:
        """Удалить только строки списка; inner Frame и BooleanVar сохраняются."""
        inner = getattr(self, "calc_picker_inner", None)
        if inner is None:
            return
        for child in inner.winfo_children():
            child.destroy()
        self._calc_picker_checkbuttons = {}
        self._calc_picker_visible_codes = []

    def _on_picker_toggle(self, code: str) -> None:
        if self._calc_picker_syncing:
            _log.debug("picker toggle ignored (syncing) code=%s", code)
            return
        var = self._calc_picker_vars.get(code)
        if var is None:
            _log.warning("picker toggle: no var for code=%s", code, extra={"tag": "Расчёт"})
            return
        checked = bool(var.get())
        _log.info(
            "picker toggle code=%s checked=%s left_before=%s",
            code,
            checked,
            len(self._calc_entries),
            extra={"tag": "Расчёт"},
        )
        try:
            if checked:
                if not any(e.code == code for e in self._calc_entries):
                    self._add_test_to_calc(code)
            else:
                entry = next((e for e in self._calc_entries if e.code == code), None)
                if entry:
                    self._remove_calc_entry(entry)
            _log.info(
                "picker toggle done code=%s left_after=%s count_label=%r",
                code,
                len(self._calc_entries),
                self.calc_count_var.get() if hasattr(self, "calc_count_var") else "",
                extra={"tag": "Расчёт"},
            )
            # гарантировать, что левая панель видна и canvas обновлён
            try:
                self._calc_canvas.update_idletasks()
                if hasattr(self, "_calc_canvas_window"):
                    self._calc_canvas.itemconfigure(
                        self._calc_canvas_window,
                        width=max(int(self._calc_canvas.winfo_width()), 1),
                    )
                self._calc_canvas.configure(scrollregion=self._calc_canvas.bbox("all"))
            except tk.TclError:
                pass
        except Exception as exc:
            _log.exception("picker toggle failed code=%s: %s", code, exc, extra={"tag": "Расчёт"})
            messagebox.showerror("Расчёт", f"Не удалось добавить испытание:\n{exc}")

    def _picker_select_suggested(self) -> None:
        """Отметить все испытания из заявки для текущей марки."""
        mark = self.mark_var.get().strip()
        if not mark:
            _log.warning("picker_select_suggested: empty mark", extra={"tag": "Расчёт"})
            messagebox.showinfo("Расчёт", "Сначала укажите марку кабеля.")
            return
        codes = self._suggested_test_codes_for_mark(mark)
        if not codes:
            _log.info(
                "picker_select_suggested: no suggested codes mark=%r",
                mark[:80],
                extra={"tag": "Расчёт"},
            )
            messagebox.showinfo(
                "Расчёт",
                "Для этой марки нет подсказок из заявки.\n"
                "Используйте поиск или «Отметить видимые».",
            )
            return
        added = 0
        for code in codes:
            if not any(e.code == code for e in self._calc_entries):
                self._add_test_to_calc(code)
                added += 1
        self._refresh_calc_picker()
        self.status.set(f"Из заявки: +{added} (всего в расчёте {len(self._calc_entries)})")

    def _picker_select_visible(self) -> None:
        """Отметить все видимые (после фильтров) испытания."""
        codes = list(getattr(self, "_calc_picker_visible_codes", []) or [])
        if not codes:
            return
        for code in codes:
            if not any(e.code == code for e in self._calc_entries):
                self._add_test_to_calc(code)
        self._refresh_calc_picker()
        self.status.set(f"Отмечено видимых: {len(codes)}")

    def _picker_clear_visible(self) -> None:
        """Снять галочки с видимых испытаний."""
        codes = set(getattr(self, "_calc_picker_visible_codes", []) or [])
        if not codes:
            return
        to_remove = [e for e in list(self._calc_entries) if e.code in codes]
        for entry in to_remove:
            self._remove_calc_entry(entry)
        self._refresh_calc_picker()
        self.status.set(f"Снято видимых: {len(to_remove)}")

    def _refresh_calc_picker(self) -> None:
        if not hasattr(self, "calc_picker_inner"):
            return
        # Не clear() BooleanVar — галочки и выбор слева должны пережить фильтр.
        self._clear_picker_rows()
        # combobox values обновляет только _update_picker_category_combo (load прайса)
        self._sync_picker_category_display(self._picker_category_filter())

        mark = self.mark_var.get().strip()
        selected = {e.code for e in self._calc_entries}
        suggested = set(self._suggested_test_codes_for_mark(mark) if mark else [])
        # синхронизировать vars с левым списком (источник истины выбора)
        for code, var in list(self._calc_picker_vars.items()):
            want = code in selected
            if bool(var.get()) != want:
                self._calc_picker_syncing = True
                try:
                    var.set(want)
                finally:
                    self._calc_picker_syncing = False

        if not mark and not selected and not self._tests_by_code:
            self._show_picker_empty(
                "Укажите марку — появятся испытания из заявки и полный справочник."
            )
            self.calc_picker_list_stats_var.set("")
            if hasattr(self, "calc_picker_stats_var"):
                self.calc_picker_stats_var.set("")
            return

        if not self._tests_by_code and not selected:
            self._show_picker_empty(
                "Справочник пуст — загрузите прайс или migrate-db."
            )
            self.calc_picker_list_stats_var.set("")
            if hasattr(self, "calc_picker_stats_var"):
                self.calc_picker_stats_var.set("")
            return

        codes = self._picker_filtered_codes(mark)
        search_text = (
            (self.calc_picker_search_var.get() if hasattr(self, "calc_picker_search_var") else "")
            or ""
        ).strip()
        cat_filter = self._picker_category_filter()
        _log.debug(
            "picker refresh: category=%r search=%r codes=%d first_codes=%r",
            cat_filter,
            search_text,
            len(codes),
            codes[:5],
        )

        if not codes:
            self._show_picker_empty(
                "Ничего не найдено. Очистите поиск или выберите категорию «Все»."
            )
            cat_bit = (
                f"категория: {CATEGORY_SHORT.get(cat_filter, cat_filter)} · "
                if cat_filter != "Все"
                else ""
            )
            self.calc_picker_list_stats_var.set(
                f"{cat_bit}показано 0 / в прайсе {len(self._tests_by_code)}"
            )
            if hasattr(self, "calc_picker_stats_var"):
                self.calc_picker_stats_var.set(f"выбрано {len(selected)} · видно 0")
            return

        self._show_picker_list()
        self._calc_picker_visible_codes = list(codes)

        by_cat: dict[str, list[str]] = {}
        for code in codes:
            test = self._tests_by_code.get(code) or {}
            cat = (test.get("category") or "Без категории").strip()
            by_cat.setdefault(cat, []).append(code)

        if suggested:
            head = f"★ из заявки: {len(suggested)}  ·  "
        else:
            head = ""
        if cat_filter != "Все":
            cat_bit = f"категория: {CATEGORY_SHORT.get(cat_filter, cat_filter)}  ·  "
        else:
            cat_bit = ""
        self.calc_picker_list_stats_var.set(
            f"{head}{cat_bit}показано {len(codes)} / в прайсе {len(self._tests_by_code)}"
        )

        for cat in sorted(by_cat.keys(), key=category_sort_key):
            cat_codes = by_cat[cat]
            short = CATEGORY_SHORT.get(cat, cat[:18])
            hdr = ttk.Frame(self.calc_picker_inner, style="Card.TFrame")
            hdr.pack(fill="x", anchor="w", pady=(6, 2))
            ttk.Label(
                hdr,
                text=f"▸ {short}  ({len(cat_codes)})",
                style="Card.TLabel",
            ).pack(side="left")
            if short != cat:
                ttk.Label(hdr, text=cat, style="CardMuted.TLabel").pack(
                    side="left", padx=(6, 0)
                )

            for code in cat_codes:
                test = self._tests_by_code.get(code) or {}
                name = (test.get("name") or code)[:64]
                is_sug = code in suggested
                prefix = "★ " if is_sug else ""
                label = f"{prefix}{name}"
                var = self._get_picker_var(code)
                self._calc_picker_syncing = True
                try:
                    var.set(code in selected)
                finally:
                    self._calc_picker_syncing = False
                row = ttk.Frame(self.calc_picker_inner, style="Card.TFrame")
                row.pack(fill="x", anchor="w", pady=0)
                # Card.TCheckbutton: видимый индикатор (см. theme); не ASCII [ ]/[x]
                cb = ttk.Checkbutton(
                    row,
                    text=label,
                    variable=var,
                    command=lambda c=code: self._on_picker_toggle(c),
                    style="Card.TCheckbutton",
                    takefocus=True,
                )
                cb.pack(side="left", anchor="w", fill="x", expand=True)
                # Клик по коду справа — тот же toggle (иногда CB «не ловит» hit-area)
                def _row_click(_event=None, c=code, v=var) -> str:
                    if self._calc_picker_syncing:
                        return "break"
                    v.set(not bool(v.get()))
                    self._on_picker_toggle(c)
                    return "break"

                code_lbl = ttk.Label(
                    row,
                    text=code,
                    style="CardMuted.TLabel",
                    width=22,
                )
                code_lbl.pack(side="right", padx=(4, 0))
                code_lbl.bind("<Button-1>", _row_click)
                self._calc_picker_checkbuttons[code] = cb

        if hasattr(self, "calc_picker_stats_var"):
            self.calc_picker_stats_var.set(
                f"выбрано {len(selected)} · видно {len(codes)}"
            )
        try:
            self._calc_picker_canvas.yview_moveto(0)
        except tk.TclError:
            pass
        self._schedule_picker_geometry()

    def _run_calculate(self) -> None:
        mark = self.mark_var.get().strip()
        if not mark:
            _log.warning(
                "calculate abort: empty mark (entry=%r left_n=%s)",
                getattr(self, "calc_mark_entry", None) and self.calc_mark_entry.get(),
                len(self._calc_entries),
                extra={"tag": "Расчёт"},
            )
            messagebox.showwarning("Расчёт", "Укажите марку кабеля.")
            return
        if not self._calc_entries:
            _log.warning(
                "calculate abort: no tests selected mark=%r picker_visible=%s",
                mark[:80],
                len(getattr(self, "_calc_picker_visible_codes", []) or []),
                extra={"tag": "Расчёт"},
            )
            messagebox.showwarning(
                "Расчёт",
                "Отметьте испытания справа (поиск / категории) или «Из заявки →».",
            )
            return

        test_list = [e.code for e in self._calc_entries]
        quantities = self._build_quantities_map()
        hours = self._build_hours_map()
        try:
            discount = float(self.calc_discount_var.get().replace(",", "."))
        except ValueError as exc:
            _log.warning(
                "calculate: bad discount %r → 0 (%s)",
                self.calc_discount_var.get(),
                exc,
                extra={"tag": "Расчёт"},
            )
            discount = 0.0
        try:
            markup = float(self.calc_markup_var.get().replace(",", "."))
        except ValueError as exc:
            _log.warning(
                "calculate: bad markup %r → 0 (%s)",
                self.calc_markup_var.get(),
                exc,
                extra={"tag": "Расчёт"},
            )
            markup = 0.0
        has_armor = self.calc_armor_var.get() or None
        self.status.set("Расчёт…")
        db_path = self.db_path
        _log.info(
            "GUI calculate start mark=%r n_tests=%s codes=%s discount=%s markup=%s "
            "armor=%s qty=%s hours_keys=%s",
            mark[:80],
            len(test_list),
            test_list,
            discount,
            markup,
            has_armor,
            quantities,
            list(hours.keys())[:12],
            extra={"tag": "Расчёт"},
        )

        def work() -> None:
            try:
                _log.info(
                    "GUI calculate worker mark=%r codes=%s",
                    mark[:80],
                    test_list,
                    extra={"tag": "Расчёт"},
                )
                calc = calculate_cost(
                    mark,
                    test_list,
                    hours,
                    db_path,
                    quantities=quantities,
                    discount_percent=discount,
                    markup_percent=markup,
                    has_armor=has_armor,
                )
                calc_id = save_calculation(calc, db_path)
                _log.info(
                    "GUI calculate ok id=%s total_with_vat=%s lines=%s",
                    calc_id,
                    calc.total_cost_with_vat,
                    len(calc.lines),
                    extra={"tag": "Расчёт"},
                )
                text = format_breakdown(calc) + f"\n\n✓ Сохранено в БД (id={calc_id})"
                try:
                    self.after(0, lambda: self._show_calc_result_mode(text))
                    self.after(0, self._load_history)
                    self.after(0, self._load_kp_calculations)
                    self.after(0, lambda: self.status.set("Расчёт выполнен"))
                except RuntimeError:
                    _log.warning(
                        "calculate done: cannot schedule after() — no main loop",
                        extra={"tag": "Расчёт"},
                    )
            except Exception as exc:
                _log.exception("GUI calculate failed: %s", exc, extra={"tag": "Расчёт"})
                try:
                    self.after(0, lambda: messagebox.showerror("Ошибка расчёта", str(exc)))
                    self.after(0, lambda: self.status.set("Ошибка"))
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _clear_calc(self) -> None:
        self._set_calc_mark_field("")
        self._clear_calc_tests()
        self._show_calc_picker_mode()
        self._set_text(self.calc_output, "")
        self._refresh_calc_picker()

    def _use_mark_in_calc(self) -> None:
        if not self._extraction_draft:
            _log.warning("use_mark_in_calc abort: no draft", extra={"tag": "Расчёт"})
            messagebox.showinfo(
                "Расчёт",
                "Сначала извлеките заявку на вкладке «1. Заявка».",
            )
            return

        entry = self._selected_draft_mark()
        if entry is None:
            n = len(self._extraction_draft.marks) if self._extraction_draft else 0
            sel = ()
            try:
                sel = self.marks_tree.selection() if hasattr(self, "marks_tree") else ()
            except tk.TclError:
                pass
            _log.warning(
                "use_mark_in_calc abort: no mark selected draft_marks=%s tree_sel=%s",
                n,
                sel,
                extra={"tag": "Расчёт"},
            )
            messagebox.showinfo(
                "Расчёт",
                "Выберите марку в таблице (клик по строке), затем «→ В расчёт» или двойной клик.",
            )
            return

        if not entry.accepted:
            _log.info(
                "use_mark_in_calc: mark not accepted, ask operator mark=%r",
                (entry.mark or "")[:60],
                extra={"tag": "Расчёт"},
            )
            if not messagebox.askyesno(
                "Марка снята",
                f"Марка «{entry.mark[:60]}» не принята (—).\nВсё равно подставить в расчёт?",
            ):
                _log.info("use_mark_in_calc abort: operator refused unaccepted", extra={"tag": "Расчёт"})
                return

        if not self._extraction_confirmed and self.confirm_only_var.get():
            _log.info(
                "use_mark_in_calc: draft not confirmed, ask operator",
                extra={"tag": "Расчёт"},
            )
            if not messagebox.askyesno(
                "Черновик",
                "Заявка ещё не подтверждена. Подставить марку из черновика?",
            ):
                _log.info("use_mark_in_calc abort: operator refused draft", extra={"tag": "Расчёт"})
                return

        mark_text = (entry.mark or "").strip()
        # Сначала вкладка «Расчёт», потом запись в поле — иначе Entry на скрытой
        # вкладке иногда не показывает textvariable (Windows/ttk).
        if hasattr(self, "go_section"):
            self.go_section("calc")
        elif self.notebook:
            self.notebook.select(self.tab_calc)
        self.update_idletasks()
        self._set_calc_mark_field(mark_text)
        self._show_calc_picker_mode()
        self._update_calc_suggestions_hint()
        self._refresh_calc_picker()
        codes = self._suggested_test_codes_for_mark(mark_text)
        shown = (self.mark_var.get() or "").strip()
        entry_shown = ""
        try:
            if hasattr(self, "calc_mark_entry"):
                entry_shown = self.calc_mark_entry.get().strip()
        except tk.TclError:
            entry_shown = "<tcl-error>"
        _log.info(
            "use_mark_in_calc mark=%r var=%r entry=%r accepted=%s suggested=%s "
            "req=%r confirmed=%s picker_codes=%s",
            mark_text[:80],
            shown[:80],
            entry_shown[:80],
            entry.accepted,
            codes,
            (entry.requirements_raw or "")[:120],
            self._extraction_confirmed,
            len(getattr(self, "_calc_picker_visible_codes", []) or []),
            extra={"tag": "Расчёт"},
        )
        if shown != mark_text or (entry_shown and entry_shown != mark_text):
            _log.warning(
                "use_mark_in_calc display mismatch mark=%r var=%r entry=%r",
                mark_text[:80],
                shown[:80],
                entry_shown[:80],
                extra={"tag": "Расчёт"},
            )
            # повторная запись + icursor
            self._set_calc_mark_field(mark_text)
        if codes:
            self.status.set(
                f"Марка «{mark_text[:40]}» · ★ из заявки: {len(codes)} — "
                "«Испытания из заявки» или галочки справа"
            )
        else:
            self.status.set(
                f"Марка «{mark_text[:40]}» в поле «Марка кабеля» — отметьте "
                "испытания справа и «Рассчитать»"
            )

    def _set_calc_mark_field(self, mark_text: str) -> None:
        """Записать марку в StringVar и гарантировать отображение в Entry."""
        text = (mark_text or "").strip()
        self.mark_var.set(text)
        entry = getattr(self, "calc_mark_entry", None)
        if entry is not None:
            try:
                # Явная синхронизация widget ← var (на случай рассинхрона ttk)
                current = entry.get()
                if current != text:
                    entry.delete(0, "end")
                    entry.insert(0, text)
                entry.icursor("end")
                entry.xview_moveto(0)
            except tk.TclError:
                pass
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def _delete_selected_calculation(self) -> None:
        sel = self.history_tree.selection()
        if not sel:
            messagebox.showinfo("История", "Выберите расчёт.")
            return
        vals = self.history_tree.item(sel[0], "values")
        calc_id = int(vals[0])
        mark = vals[2] if len(vals) > 2 else ""
        if not messagebox.askyesno(
            "Удалить расчёт",
            f"Удалить расчёт №{calc_id}?\n{mark}\n\nСвязи в заказах будут отвязаны.",
        ):
            return
        result = delete_calculation(calc_id, self.db_path)
        if result.get("ok"):
            self._load_history()
            self._load_kp_calculations()
            self.status.set(f"Расчёт №{calc_id} удалён")
            _log.info("deleted calculation id=%s", calc_id, extra={"tag": "БД"})
        else:
            messagebox.showerror("История", f"Не удалось: {result.get('reason')}")

