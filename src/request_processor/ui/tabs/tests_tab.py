"""Mixin: TestsTabMixin — domain methods for Lab_request GUI."""

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

class TestsTabMixin:
    def _build_tests_tab(self) -> None:
        # Компактный тулбар: поиск + главные действия; остальное — «Ещё» и ПКМ
        toolbar = ttk.Frame(self.tab_tests)
        toolbar.pack(fill="x", pady=(0, 8))

        self.tests_search_var = tk.StringVar()
        self.tests_search_var.trace_add("write", lambda *_: self._load_tests())
        ttk.Label(toolbar, text="Поиск").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.tests_search_var, width=36).pack(
            side="left", padx=(6, 10), ipady=2
        )
        self._accent_button(toolbar, "В расчёт", self._add_selected_test_to_calc).pack(side="left")
        ttk.Button(toolbar, text="Добавить…", command=self._add_test_dialog).pack(side="left", padx=6)

        more = ttk.Menubutton(toolbar, text="Ещё ▾")
        more_menu = tk.Menu(more, tearoff=0)
        more_menu.add_command(label="Обновить список", command=self._load_tests)
        more_menu.add_separator()
        more_menu.add_command(label="Развернуть все", command=self._expand_all_categories)
        more_menu.add_command(label="Свернуть все", command=self._collapse_all_categories)
        more["menu"] = more_menu
        more.pack(side="left", padx=(4, 0))

        self.calc_count_var = tk.StringVar(value="В расчёте: 0")
        ttk.Label(toolbar, textvariable=self.calc_count_var, style="Muted.TLabel").pack(
            side="right"
        )
        ttk.Label(
            toolbar, text="Двойной клик / ПКМ — в расчёт", style="Muted.TLabel"
        ).pack(side="right", padx=(0, 12))

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
        self.tests_tree.bind("<Button-3>", self._on_tests_context_menu)

    def _selected_test_code(self) -> str | None:
        sel = self.tests_tree.selection()
        if not sel:
            return None
        iid = str(sel[0])
        if iid.startswith("cat::"):
            return None
        if iid.startswith("test::"):
            return iid.removeprefix("test::")
        return iid

    def _add_selected_test_to_calc(self) -> None:
        code = self._selected_test_code()
        if not code:
            messagebox.showinfo("Справочник", "Выберите испытание (не категорию).")
            return
        self._add_test_to_calc(code)

    def _on_tests_context_menu(self, event: tk.Event) -> None:
        row = self.tests_tree.identify_row(event.y)
        if row:
            self.tests_tree.selection_set(row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Добавить в расчёт", command=self._add_selected_test_to_calc)
        menu.add_separator()
        menu.add_command(label="Развернуть все", command=self._expand_all_categories)
        menu.add_command(label="Свернуть все", command=self._collapse_all_categories)
        menu.add_command(label="Обновить", command=self._load_tests)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _add_test_to_calc(self, code: str) -> None:
        test = self._tests_by_code.get(code)
        if not test:
            messagebox.showwarning("Справочник", f"Испытание «{code}» не найдено.")
            return

        existing = self._find_calc_entry(code)
        if existing and existing.quantity_var is not None:
            try:
                current = int(existing.quantity_var.get())
                existing.quantity_var.set(str(current + 1))
            except ValueError:
                existing.quantity_var.set("2")
            self.status.set(f"Количество «{test['name'][:40]}»: +1")
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
            quantity_var=tk.StringVar(value="1"),
        )
        self._calc_entries.append(entry)
        self._render_calc_entry(entry, len(self._calc_entries) - 1)
        self._hide_calc_empty_hint()
        self._sync_picker_var(entry.code, True)

        self._update_calc_count_label()
        self.status.set(f"Добавлено в расчёт: {test['name'][:50]} (остаётесь в справочнике)")

    def _expand_all_categories(self) -> None:
        for item in self.tests_tree.get_children(""):
            self.tests_tree.item(item, open=True)

    def _collapse_all_categories(self) -> None:
        for item in self.tests_tree.get_children(""):
            self.tests_tree.item(item, open=False)

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
        self._refresh_calc_picker()

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

