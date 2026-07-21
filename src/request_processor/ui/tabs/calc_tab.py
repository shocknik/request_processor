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
        self.mark_var = tk.StringVar()
        mark_row = ttk.Frame(inner, style="Card.TFrame")
        mark_row.pack(fill="x")
        mark_entry = ttk.Entry(mark_row, textvariable=self.mark_var, font=("Segoe UI", 11))
        mark_entry.pack(side="left", fill="x", expand=True, ipady=4)
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
        ttk.Checkbutton(
            opts,
            text="Бронированный кабель (+0.5 к сложности образца)",
            variable=self.calc_armor_var,
            style="Card.TCheckbutton",
        ).pack(side="left")
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

        self.calc_right_panel = ttk.LabelFrame(
            mid, text="Испытания для расчёта", padding=8, style="Card.TLabelframe"
        )
        mid.add(self.calc_right_panel, weight=2)

        self.calc_picker_frame = ttk.Frame(self.calc_right_panel, style="Card.TFrame")
        ttk.Label(
            self.calc_picker_frame,
            text="Отметьте испытания — они появятся слева (часы для климатики).",
            style="CardMuted.TLabel",
            wraplength=420,
        ).pack(anchor="w", pady=(0, 6))

        picker_canvas_frame = ttk.Frame(self.calc_picker_frame, style="Card.TFrame")
        picker_canvas_frame.pack(fill="both", expand=True)
        self._calc_picker_canvas = tk.Canvas(
            picker_canvas_frame,
            bg=COLORS["card"],
            highlightthickness=0,
            borderwidth=0,
        )
        picker_scroll = ttk.Scrollbar(
            picker_canvas_frame, orient="vertical", command=self._calc_picker_canvas.yview
        )
        self.calc_picker_inner = ttk.Frame(self._calc_picker_canvas, style="Card.TFrame")
        self.calc_picker_inner.bind(
            "<Configure>",
            lambda e: self._calc_picker_canvas.configure(
                scrollregion=self._calc_picker_canvas.bbox("all")
            ),
        )
        self._calc_picker_canvas.create_window((0, 0), window=self.calc_picker_inner, anchor="nw")
        self._calc_picker_canvas.configure(yscrollcommand=picker_scroll.set)
        self._calc_picker_canvas.pack(side="left", fill="both", expand=True)
        picker_scroll.pack(side="right", fill="y")

        self.calc_picker_empty_var = tk.StringVar(
            value="Укажите марку — появятся испытания из заявки или полный справочник."
        )
        self._calc_picker_empty_label = ttk.Label(
            self.calc_picker_inner,
            textvariable=self.calc_picker_empty_var,
            style="CardMuted.TLabel",
            wraplength=400,
            justify="left",
        )
        self._calc_picker_empty_label.pack(anchor="w", pady=8)

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

    def _picker_candidate_codes(self, mark: str) -> list[str]:
        suggested = self._suggested_test_codes_for_mark(mark)
        selected = [e.code for e in self._calc_entries]
        if suggested:
            merged = list(dict.fromkeys(suggested + selected))
            return merged
        if not self._tests_by_code:
            return selected
        return sorted(
            self._tests_by_code.keys(),
            key=lambda c: (
                self._tests_by_code[c].get("category") or "",
                self._tests_by_code[c].get("name") or c,
            ),
        )

    def _sync_picker_var(self, code: str, checked: bool) -> None:
        var = self._calc_picker_vars.get(code)
        if var is None:
            return
        self._calc_picker_syncing = True
        try:
            var.set(checked)
        finally:
            self._calc_picker_syncing = False

    def _on_picker_toggle(self, code: str) -> None:
        if self._calc_picker_syncing:
            return
        var = self._calc_picker_vars.get(code)
        if var is None:
            return
        if var.get():
            if not any(e.code == code for e in self._calc_entries):
                self._add_test_to_calc(code)
        else:
            entry = next((e for e in self._calc_entries if e.code == code), None)
            if entry:
                self._remove_calc_entry(entry)

    def _refresh_calc_picker(self) -> None:
        if not hasattr(self, "calc_picker_inner"):
            return
        for child in self.calc_picker_inner.winfo_children():
            if child is not self._calc_picker_empty_label:
                child.destroy()
        self._calc_picker_vars.clear()

        mark = self.mark_var.get().strip()
        codes = self._picker_candidate_codes(mark) if mark else []
        suggested = set(self._suggested_test_codes_for_mark(mark)) if mark else set()
        selected = {e.code for e in self._calc_entries}

        if not codes:
            self._calc_picker_empty_label.pack(anchor="w", pady=8)
            self.calc_picker_empty_var.set(
                "Укажите марку — появятся испытания из заявки или полный справочник."
            )
            return

        self._calc_picker_empty_label.pack_forget()
        if suggested:
            hint = f"Из заявки ({len(suggested)}); отмеченные добавляются в список слева."
        else:
            hint = f"Справочник ({len(codes)} испытаний); отметьте нужные."
        ttk.Label(
            self.calc_picker_inner,
            text=hint,
            style="CardMuted.TLabel",
            wraplength=400,
        ).pack(anchor="w", pady=(0, 4))

        for code in codes:
            test = self._tests_by_code.get(code)
            if not test:
                continue
            name = (test.get("name") or code)[:72]
            var = tk.BooleanVar(value=code in selected)
            self._calc_picker_vars[code] = var
            row = ttk.Frame(self.calc_picker_inner, style="Card.TFrame")
            row.pack(fill="x", anchor="w", pady=1)
            cb = ttk.Checkbutton(
                row,
                text=f"{code} — {name}",
                variable=var,
                command=lambda c=code: self._on_picker_toggle(c),
            )
            cb.pack(anchor="w")

    def _run_calculate(self) -> None:
        mark = self.mark_var.get().strip()
        if not mark:
            messagebox.showwarning("Расчёт", "Укажите марку кабеля.")
            return
        if not self._calc_entries:
            messagebox.showwarning("Расчёт", "Добавьте испытания из справочника (двойной клик).")
            return

        test_list = [e.code for e in self._calc_entries]
        quantities = self._build_quantities_map()
        hours = self._build_hours_map()
        try:
            discount = float(self.calc_discount_var.get().replace(",", "."))
        except ValueError:
            discount = 0.0
        try:
            markup = float(self.calc_markup_var.get().replace(",", "."))
        except ValueError:
            markup = 0.0
        has_armor = self.calc_armor_var.get() or None
        self.status.set("Расчёт…")

        def work() -> None:
            try:
                _log.info(
                    "GUI calculate mark=%r codes=%s",
                    mark[:80],
                    test_list,
                    extra={"tag": "Расчёт"},
                )
                calc = calculate_cost(
                    mark,
                    test_list,
                    hours,
                    self.db_path,
                    quantities=quantities,
                    discount_percent=discount,
                    markup_percent=markup,
                    has_armor=has_armor,
                )
                calc_id = save_calculation(calc, self.db_path)
                _log.info(
                    "GUI calculate ok id=%s total_with_vat=%s lines=%s",
                    calc_id,
                    calc.total_cost_with_vat,
                    len(calc.lines),
                    extra={"tag": "Расчёт"},
                )
                text = format_breakdown(calc) + f"\n\n✓ Сохранено в БД (id={calc_id})"
                self.after(0, lambda: self._show_calc_result_mode(text))
                self.after(0, self._load_history)
                self.after(0, self._load_kp_calculations)
                self.after(0, lambda: self.status.set("Расчёт выполнен"))
            except Exception as exc:
                _log.exception("GUI calculate failed: %s", exc, extra={"tag": "Расчёт"})
                self.after(0, lambda: messagebox.showerror("Ошибка расчёта", str(exc)))
                self.after(0, lambda: self.status.set("Ошибка"))

        threading.Thread(target=work, daemon=True).start()

    def _clear_calc(self) -> None:
        self.mark_var.set("")
        self._clear_calc_tests()
        self._show_calc_picker_mode()
        self._set_text(self.calc_output, "")
        self._refresh_calc_picker()

    def _use_mark_in_calc(self) -> None:
        if not self._extraction_draft:
            messagebox.showinfo(
                "Расчёт",
                "Сначала извлеките заявку на вкладке «1. Заявка».",
            )
            return

        entry = self._selected_draft_mark()
        if entry is None:
            messagebox.showinfo(
                "Расчёт",
                "Выберите марку в таблице (клик по строке), затем «→ В расчёт» или двойной клик.",
            )
            return

        if not entry.accepted:
            if not messagebox.askyesno(
                "Марка снята",
                f"Марка «{entry.mark[:60]}» не принята (—).\nВсё равно подставить в расчёт?",
            ):
                return

        if not self._extraction_confirmed and self.confirm_only_var.get():
            if not messagebox.askyesno(
                "Черновик",
                "Заявка ещё не подтверждена. Подставить марку из черновика?",
            ):
                return

        mark_text = entry.mark
        self.mark_var.set(mark_text)
        if self.notebook:
            self.notebook.select(self.tab_calc)
        self._update_calc_suggestions_hint()
        codes = self._suggested_test_codes_for_mark(mark_text)
        if codes:
            self.status.set(
                f"Марка подставлена · из заявки: {', '.join(codes)} — «Испытания из заявки»"
            )
        else:
            self.status.set("Марка подставлена в расчёт — нажмите «Рассчитать»")

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

