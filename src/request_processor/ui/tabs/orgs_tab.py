"""Mixin: OrgsTabMixin — domain methods for Lab_request GUI."""

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
    find_similar_organizations,
    find_organization_id_by_name,
    create_organization,
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

class OrgsTabMixin:
    def _build_orgs_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_orgs)
        toolbar.pack(fill="x", pady=(0, 8))
        self.orgs_search_var = tk.StringVar()
        self.orgs_search_var.trace_add("write", lambda *_: self._load_orgs_table())
        ttk.Label(toolbar, text="Поиск").pack(side="left")
        ttk.Entry(toolbar, textvariable=self.orgs_search_var, width=36).pack(
            side="left", padx=(6, 10), ipady=2
        )
        self._accent_button(toolbar, "+ Добавить…", self._add_organization).pack(side="left")
        self._accent_button(toolbar, "Редактировать…", self._edit_selected_organization).pack(
            side="left", padx=(8, 0)
        )
        more = ttk.Menubutton(toolbar, text="Ещё ▾")
        more_menu = tk.Menu(more, tearoff=0)
        more_menu.add_command(label="Обновить", command=self._load_orgs_table)
        more_menu.add_command(label="Удалить…", command=self._delete_selected_organization)
        more["menu"] = more_menu
        more.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, text="CRUD · дедуп по имени · Двойной клик / ПКМ", style="Muted.TLabel").pack(
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
        for col, title, width, anchor, stretch in (
            ("name", "Название", 320, "w", True),
            ("inn", "ИНН", 110, "w", False),
            ("org_type", "Тип", 130, "w", False),
            ("accredited", "Аккред.", 70, "center", False),
            ("address", "Адрес", 280, "w", True),
            ("phone", "Телефон", 120, "w", False),
            ("fsa", "Реестр ФСА", 150, "w", False),
        ):
            self.orgs_tree.heading(col, text=title, anchor=anchor)
            self.orgs_tree.column(col, width=width, anchor=anchor, stretch=stretch, minwidth=width)
        self.orgs_tree.pack(fill="both", expand=True)
        self.orgs_tree.bind("<Double-Button-1>", lambda _e: self._edit_selected_organization())
        self.orgs_tree.bind("<Button-3>", self._on_orgs_context_menu)

    def _on_orgs_context_menu(self, event: tk.Event) -> None:
        row = self.orgs_tree.identify_row(event.y)
        if row:
            self.orgs_tree.selection_set(row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="+ Добавить…", command=self._add_organization)
        menu.add_command(label="Редактировать…", command=self._edit_selected_organization)
        menu.add_separator()
        menu.add_command(label="Удалить…", command=self._delete_selected_organization)
        menu.add_command(label="Обновить", command=self._load_orgs_table)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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

    def _add_organization(self) -> None:
        """CRUD: создать организацию (с fuzzy-дедупом по названию)."""
        self._open_organization_editor(None)

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

    def _open_organization_editor(self, row: dict | None) -> None:
        is_new = row is None
        dialog = tk.Toplevel(self)
        title_name = (row or {}).get("name", "новая") if row else "новая"
        dialog.title(
            "Новая организация" if is_new else f"Организация — {str(title_name)[:40]}"
        )
        dialog.geometry("520x540")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()

        row = row or {}
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
        r += 1
        if is_new:
            ttk.Label(
                form,
                text="При сохранении проверим похожие названия в справочнике.",
                style="Muted.TLabel",
            ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def save() -> None:
            name = fields["name"].get().strip()
            if len(name) < 2:
                messagebox.showwarning("Организации", "Укажите название организации.")
                return

            from ...generation.lab_profile import is_own_lab_name

            if is_own_lab_name(name):
                messagebox.showinfo(
                    "Организации",
                    "Это наша ИЛ (Кабель-Тест / lab_profile).\n"
                    "Её не добавляют в справочник заказчиков — реквизиты в lab_profile.yaml.",
                )
                return

            payload = dict(
                name=name,
                address=fields["address"].get().strip() or None,
                postal_code=fields["postal_code"].get().strip() or None,
                phone=fields["phone"].get().strip() or None,
                email=fields["email"].get().strip() or None,
                inn=fields["inn"].get().strip() or None,
                kpp=fields["kpp"].get().strip() or None,
                is_accredited=bool(fields["is_accredited"].get()),
                fsa_registry_number=fields["fsa_registry_number"].get().strip() or None,
                org_type=fields["org_type"].get(),
            )

            if is_new:
                exact = find_organization_id_by_name(name, db_path=self.db_path)
                if exact is not None:
                    if not messagebox.askyesno(
                        "Организации",
                        f"Точное совпадение уже есть (id={exact}).\n"
                        f"Открыть существующую для редактирования?",
                    ):
                        return
                    dialog.destroy()
                    existing = get_organization_by_id(exact, self.db_path)
                    if existing:
                        self._open_organization_editor(existing)
                    return
                similar = [
                    s
                    for s in find_similar_organizations(
                        name, min_ratio=0.82, limit=5, db_path=self.db_path
                    )
                    if s.get("score", 0) < 1.0
                ]
                if similar:
                    lines = "\n".join(
                        f"  • {s['name']} ({s['score']:.0%})" for s in similar[:5]
                    )
                    ans = messagebox.askyesnocancel(
                        "Похожая организация",
                        f"«{name}»\n\nПохожие в справочнике:\n{lines}\n\n"
                        f"Да — открыть «{similar[0]['name']}»\n"
                        f"Нет — всё равно создать новую\n"
                        f"Отмена — назад к форме",
                        parent=dialog,
                    )
                    if ans is True:
                        dialog.destroy()
                        existing = get_organization_by_id(int(similar[0]["id"]), self.db_path)
                        if existing:
                            self._open_organization_editor(existing)
                        return
                    if ans is None:
                        return
                try:
                    new_id = create_organization(
                        **payload, source="manual_gui", db_path=self.db_path
                    )
                except Exception as exc:
                    messagebox.showerror("Организации", f"Не удалось создать: {exc}")
                    return
                dialog.destroy()
                self._load_organizations()
                self.status.set(f"Организация добавлена id={new_id}: {name[:50]}")
                _log.info(
                    "created organization id=%s name=%s",
                    new_id,
                    name[:80],
                    extra={"tag": "БД"},
                )
                return

            ok = update_organization(
                int(row["id"]),
                **payload,
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
        ttk.Button(
            btns,
            text="Создать" if is_new else "Сохранить",
            style="Accent.TButton",
            command=save,
        ).pack(side="left")
        ttk.Button(btns, text="Отмена", command=dialog.destroy).pack(side="left", padx=8)

    def _fill_draft_org_fields(self, draft: ExtractionDraft) -> None:
        report = draft.report
        self.draft_customer_var.set(report.customer_name)
        self.draft_manufacturer_var.set(report.manufacturer_name)
        self.draft_recipient_var.set(report.recipient_name or "—")

        customer_org = next((o for o in report.organizations if o.role == "customer"), None)
        self.draft_customer_inn_var.set(customer_org.inn if customer_org and customer_org.inn else "")
        addr = ""
        if customer_org and customer_org.address:
            from ...extraction.organization_extractor import finalize_organization_address
            from ...models import OrganizationExtract

            source_text = self._extraction_draft.result.text if self._extraction_draft else ""
            fixed = finalize_organization_address(
                OrganizationExtract(
                    name=customer_org.name,
                    address=customer_org.address,
                    role="customer",
                ),
                source_text,
            )
            addr = fixed.address or customer_org.address
        self.draft_customer_addr_var.set(addr)

    def _delete_selected_organization(self) -> None:
        sel = self.orgs_tree.selection()
        if not sel:
            messagebox.showinfo("Организации", "Выберите организацию.")
            return
        org_id = int(sel[0])
        vals = self.orgs_tree.item(sel[0], "values")
        name = vals[0] if vals else str(org_id)
        if not messagebox.askyesno(
            "Удалить организацию",
            f"Удалить?\n\n{name}\n\nСвязи в заказах/извлечениях будут отвязаны.",
        ):
            return
        result = delete_organization(org_id, self.db_path, force=True)
        if result.get("ok"):
            self._load_organizations()
            self.status.set(f"Организация удалена: {result.get('name', name)}")
            _log.info("deleted organization id=%s", org_id, extra={"tag": "БД"})
        else:
            messagebox.showerror("Организации", f"Не удалось: {result.get('reason')}")

