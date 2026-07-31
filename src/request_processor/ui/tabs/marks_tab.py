"""Mixin: MarksTabMixin — domain methods for Lab_request GUI."""

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

class MarksTabMixin:
    def _build_marks_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_marks)
        toolbar.pack(fill="x")
        self.marks_search_var = tk.StringVar()
        self.marks_search_var.trace_add("write", lambda *_: self._load_cable_marks())
        ttk.Label(toolbar, text="Поиск").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.marks_search_var, width=36).pack(
            side="left", padx=(6, 10), ipady=2
        )
        self._accent_button(toolbar, "В расчёт", self._use_db_mark_in_calc).pack(side="left")
        ttk.Button(toolbar, text="Редактировать…", command=self._edit_selected_cable_mark).pack(
            side="left", padx=(8, 0)
        )
        more = ttk.Menubutton(toolbar, text="Ещё ▾")
        more_menu = tk.Menu(more, tearoff=0)
        more_menu.add_command(label="Обновить", command=self._load_cable_marks)
        more_menu.add_command(label="Редактировать…", command=self._edit_selected_cable_mark)
        more_menu.add_command(label="Удалить…", command=self._delete_selected_cable_mark)
        more["menu"] = more_menu
        more.pack(side="left", padx=(8, 0))
        ttk.Label(
            toolbar,
            text="Двойной клик — правка · ПКМ — меню",
            style="Muted.TLabel",
        ).pack(side="right")

        cols = ("full_mark", "brand", "fire_class", "cores", "element", "size", "document")
        self.cable_marks_tree = ttk.Treeview(self.tab_marks, columns=cols, show="headings", height=24)
        for col, title, width, stretch in (
            ("full_mark", "Усл. обозначение", 320, True),
            ("brand", "Марка", 90, False),
            ("fire_class", "Пожарный класс", 100, False),
            ("cores", "ТПЖ", 50, False),
            ("element", "Элемент", 80, False),
            ("size", "Размер", 90, False),
            ("document", "Документ", 220, True),
        ):
            self.cable_marks_tree.heading(col, text=title)
            self.cable_marks_tree.column(col, width=width, anchor="w", stretch=stretch, minwidth=width)
        self.cable_marks_tree.pack(fill="both", expand=True, pady=(8, 0))
        self.cable_marks_tree.bind("<Double-Button-1>", lambda _e: self._edit_selected_cable_mark())
        self.cable_marks_tree.bind("<Button-3>", self._on_marks_context_menu)

    def _on_marks_context_menu(self, event: tk.Event) -> None:
        row = self.cable_marks_tree.identify_row(event.y)
        if row:
            self.cable_marks_tree.selection_set(row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Редактировать…", command=self._edit_selected_cable_mark)
        menu.add_command(label="В расчёт", command=self._use_db_mark_in_calc)
        menu.add_separator()
        menu.add_command(label="Удалить…", command=self._delete_selected_cable_mark)
        menu.add_command(label="Обновить", command=self._load_cable_marks)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _use_db_mark_in_calc(self) -> None:
        sel = self.cable_marks_tree.selection()
        if not sel:
            return
        self.mark_var.set(self.cable_marks_tree.item(sel[0], "values")[0])
        if self.notebook:
            self.notebook.select(self.tab_calc)
        self.status.set("Марка из БД подставлена в расчёт")

    def _edit_selected_cable_mark(self) -> None:
        """Редактор строки справочника cable_marks (двойной клик / ПКМ)."""
        sel = self.cable_marks_tree.selection()
        if not sel:
            messagebox.showinfo("Марки", "Выберите марку в таблице.")
            return
        mark_id = int(sel[0])
        from ...persistence.sqlite_repo import get_cable_mark_by_id, update_cable_mark

        row = get_cable_mark_by_id(mark_id, self.db_path)
        if not row:
            messagebox.showerror("Марки", "Запись не найдена (обновите список).")
            self._load_cable_marks()
            return

        from ..modal import create_modal, present_modal

        dialog = create_modal(self, title="Редактировать марку", minsize=(520, 480))
        btns = ttk.Frame(dialog, padding=(12, 8, 12, 12))
        btns.pack(side="bottom", fill="x")

        fields: dict[str, tk.Variable] = {
            "mark": tk.StringVar(master=dialog, value=row.get("full_mark") or ""),
            "brand": tk.StringVar(master=dialog, value=row.get("brand") or ""),
            "fire_class": tk.StringVar(master=dialog, value=row.get("fire_class") or ""),
            "cores_count": tk.StringVar(
                master=dialog, value=str(row.get("cores_count") or "")
            ),
            "structural_element_type": tk.StringVar(
                master=dialog,
                value=row.get("structural_element_type") or "жила",
            ),
            "structural_elements_count": tk.StringVar(
                master=dialog,
                value=str(row.get("structural_elements_count") or ""),
            ),
            "characteristic_size": tk.StringVar(
                master=dialog,
                value=str(row.get("characteristic_size") or "").replace(".", ","),
            ),
            "size_unit": tk.StringVar(
                master=dialog, value=row.get("size_unit") or "mm2"
            ),
            "document": tk.StringVar(master=dialog, value=row.get("document") or ""),
        }

        form = ttk.Frame(dialog, padding=12)
        form.pack(side="top", fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(
            form,
            text="Правка справочника. Id записи сохраняется.",
            style="Muted.TLabel",
            wraplength=480,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        rows_spec = (
            ("Условное обозначение:", "mark"),
            ("Марка (бренд):", "brand"),
            ("Пожарный класс:", "fire_class"),
            ("ТПЖ (жил):", "cores_count"),
            ("Элемент:", "structural_element_type"),
            ("Кол-во элементов:", "structural_elements_count"),
            ("Размер:", "characteristic_size"),
            ("Единица:", "size_unit"),
            ("ТУ / ГОСТ:", "document"),
        )
        for r_i, (label, key) in enumerate(rows_spec, start=1):
            ttk.Label(form, text=label).grid(
                row=r_i, column=0, sticky="w", pady=4, padx=(0, 8)
            )
            if key == "structural_element_type":
                ttk.Combobox(
                    form,
                    textvariable=fields[key],
                    values=("жила", "пара", "тройка"),
                    state="readonly",
                    width=24,
                ).grid(row=r_i, column=1, sticky="ew", pady=4)
            elif key == "size_unit":
                ttk.Combobox(
                    form,
                    textvariable=fields[key],
                    values=("mm2", "mm"),
                    state="readonly",
                    width=24,
                ).grid(row=r_i, column=1, sticky="w", pady=4)
            else:
                ttk.Entry(form, textvariable=fields[key]).grid(
                    row=r_i, column=1, sticky="ew", pady=4
                )

        def do_save() -> None:
            size_raw = fields["characteristic_size"].get().strip().replace(",", ".")
            cores_raw = fields["cores_count"].get().strip()
            elem_raw = fields["structural_elements_count"].get().strip()
            try:
                cores = int(cores_raw) if cores_raw else 1
                size = float(size_raw) if size_raw else 1.0
                elem = int(elem_raw) if elem_raw else cores
            except ValueError:
                messagebox.showwarning(
                    "Марки",
                    "ТПЖ, кол-во элементов и размер должны быть числами.",
                    parent=dialog,
                )
                return
            result = update_cable_mark(
                mark_id,
                full_mark=fields["mark"].get(),
                brand=fields["brand"].get(),
                fire_class=fields["fire_class"].get() or None,
                cores_count=cores,
                structural_element_type=fields["structural_element_type"].get(),
                structural_elements_count=elem,
                characteristic_size=size,
                size_unit=fields["size_unit"].get() or "mm2",
                document=fields["document"].get() or None,
                db_path=self.db_path,
            )
            if not result.get("ok"):
                reason = result.get("reason")
                msg = {
                    "empty_mark": "Укажите условное обозначение.",
                    "duplicate_mark": "Такое обозначение уже есть у другой записи.",
                    "bad_size": "Некорректный размер / ТПЖ.",
                    "not_found": "Запись не найдена.",
                }.get(str(reason), f"Не сохранено: {reason}")
                messagebox.showerror("Марки", msg, parent=dialog)
                return
            dialog.destroy()
            self._load_cable_marks()
            try:
                self.cable_marks_tree.selection_set(str(mark_id))
                self.cable_marks_tree.see(str(mark_id))
            except tk.TclError:
                pass
            self.status.set(f"Марка обновлена: {result.get('full_mark')}")
            _log.info(
                "updated cable_mark id=%s full_mark=%r",
                mark_id,
                result.get("full_mark"),
                extra={"tag": "БД"},
            )

        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=do_save).pack(
            side="left"
        )
        ttk.Button(btns, text="Отмена", command=dialog.destroy).pack(side="left", padx=8)
        present_modal(dialog, parent=self)

    def _load_cable_marks(self) -> None:
        for item in self.cable_marks_tree.get_children():
            self.cable_marks_tree.delete(item)
        search = self.marks_search_var.get().strip() or None
        for row in list_cable_marks(search=search, limit=500, db_path=self.db_path):
            unit = "мм²" if row.get("size_unit") == "mm2" else "мм"
            self.cable_marks_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
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

    def _delete_selected_cable_mark(self) -> None:
        sel = self.cable_marks_tree.selection()
        if not sel:
            messagebox.showinfo("Марки", "Выберите марку в таблице.")
            return
        mark_id = int(sel[0])
        vals = self.cable_marks_tree.item(sel[0], "values")
        label = vals[0] if vals else str(mark_id)
        if not messagebox.askyesno(
            "Удалить марку",
            f"Удалить из справочника?\n\n{label}\n\n"
            "Если марка есть в заказах — связи будут отвязаны.",
        ):
            return
        result = delete_cable_mark(mark_id, self.db_path, force=True)
        if result.get("ok"):
            self._load_cable_marks()
            self.status.set(f"Марка удалена: {result.get('full_mark', label)}")
            _log.info("deleted cable_mark id=%s", mark_id, extra={"tag": "БД"})
        else:
            messagebox.showerror("Марки", f"Не удалось удалить: {result.get('reason')}")

