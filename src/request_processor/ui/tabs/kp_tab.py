"""Mixin: KpTabMixin — domain methods for Lab_request GUI."""

from __future__ import annotations

import json
import re
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

class KpTabMixin:
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
        self.kp_customer_var = tk.StringVar(master=self, value="")
        self.kp_customer_combo = ttk.Combobox(
            grid,
            textvariable=self.kp_customer_var,
            font=("Segoe UI", 10),
        )
        self.kp_customer_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4, ipady=2)
        ttk.Button(grid, text="↻", width=3, command=self._load_organizations).grid(
            row=0, column=2, padx=(4, 0), pady=4
        )

        ttk.Label(grid, text="Вид испытаний:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=4
        )
        self.kp_test_type_var = tk.StringVar(master=self, value="Периодические")
        self.kp_test_type_combo = ttk.Combobox(
            grid,
            textvariable=self.kp_test_type_var,
            values=list(TEST_TYPE_OPTIONS),
            state="readonly",
            font=("Segoe UI", 10),
        )
        self.kp_test_type_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4, ipady=2)
        self.kp_test_type_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_kp_preview())

        ttk.Label(grid, text="Примечание:", style="Card.TLabel").grid(
            row=2, column=0, sticky="nw", pady=4
        )
        self.kp_note_text = scrolledtext.ScrolledText(grid, height=3, font=("Segoe UI", 10))
        self.kp_note_text.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

        action = ttk.Frame(self.tab_kp)
        action.pack(fill="x", pady=(0, 8))

        ttk.Label(action, text="Стиль бланка:", style="Muted.TLabel").pack(side="left", padx=(0, 4))
        from ...generation.lab_profile import KP_STYLES, load_lab_profile

        self.kp_style_var = tk.StringVar(master=self, value=load_lab_profile().kp_style)
        ttk.Combobox(
            action,
            textvariable=self.kp_style_var,
            values=list(KP_STYLES),
            width=10,
            state="readonly",
        ).pack(side="left", padx=(0, 10))
        self._accent_button(action, "Сформировать КП", self._run_generate_kp).pack(side="left")
        more = ttk.Menubutton(action, text="Ещё ▾")
        more_menu = tk.Menu(more, tearoff=0)
        more_menu.add_command(label="Обновить список расчётов", command=self._load_kp_calculations)
        more_menu.add_command(label="Выбрать все", command=self._select_all_kp_calcs)
        more_menu.add_separator()
        more_menu.add_command(label="3 образца бланка (classic/modern/compact)…", command=self._generate_kp_style_previews)
        more["menu"] = more_menu
        more.pack(side="left", padx=(8, 0))
        ttk.Label(
            action,
            text=f"Папка: {self.generated_dir}",
            style="Muted.TLabel",
        ).pack(side="right", padx=(12, 0))

        self.kp_preview_var = tk.StringVar(
            master=self,
            value="Выберите расчёты из списка (Ctrl+клик — несколько)",
        )
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

    def _generate_kp_style_previews(self) -> None:
        try:
            from ...generation.kp_generator import render_kp_style_previews

            paths = render_kp_style_previews()
            folder = paths[0].parent if paths else None
            self.status.set(f"Образцы КП: {len(paths)} шт.")
            msg = "Сгенерированы бланки (выберите стиль в lab_profile.yaml → kp_style):\n\n"
            msg += "\n".join(f"  • {p.name}" for p in paths)
            if folder:
                msg += f"\n\nПапка:\n{folder}"
            messagebox.showinfo("Образцы КП", msg)
            if folder:
                try:
                    import os

                    os.startfile(str(folder))
                except OSError:
                    pass
        except Exception as exc:
            messagebox.showerror("Образцы КП", str(exc))

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

    def _kp_subject_text(self) -> str:
        return build_kp_subject(test_type=self.kp_test_type_var.get())

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
                subject=self._kp_subject_text(),
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
            n_loaded = len(self.kp_calc_tree.get_children()) if hasattr(self, "kp_calc_tree") else -1
            _log.warning(
                "KP abort: no calc selected (tree_n=%s)",
                n_loaded,
                extra={"tag": "КП"},
            )
            messagebox.showwarning(
                "КП",
                "Выберите один или несколько расчётов в таблице ниже (Ctrl+клик).\n\n"
                "Если список пуст — сначала выполните расчёт на вкладке «2. Расчёт».",
            )
            return

        if (
            self.confirm_only_var.get()
            and self._extraction_draft
            and not self._extraction_confirmed
        ):
            _log.warning(
                "KP abort: extraction not confirmed (confirm_only=True)",
                extra={"tag": "КП"},
            )
            messagebox.showwarning(
                "КП",
                "Сначала подтвердите заявку на вкладке «1. Заявка» "
                "(кнопка «Принять и сохранить»).",
            )
            return

        customer = self.kp_customer_var.get().strip()
        subject = self._kp_subject_text()
        note = self.kp_note_text.get("1.0", "end").strip() or None

        if not customer:
            _log.warning("KP: empty customer, ask operator", extra={"tag": "КП"})
            if not messagebox.askyesno(
                "КП",
                "Заказчик не указан — файл будет «КП_заказчик_…», "
                "в документе поле заказчика пустое.\n\n"
                "Продолжить без заказчика?\n"
                "(Нет — вернитесь и выберите/введите заказчика.)",
            ):
                _log.info("KP abort: operator refused empty customer", extra={"tag": "КП"})
                return

        from ...generation.document_pack import safe_filename_part

        safe_customer = safe_filename_part(customer, max_len=40, default="заказчик")
        out_dir = self.generated_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"КП_{safe_customer}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"

        self.status.set("Формирование КП…")
        self.update_idletasks()
        _log.info(
            "KP generate calc_ids=%s customer=%r subject=%r out=%s",
            ids,
            customer[:80],
            subject[:80],
            out_file,
            extra={"tag": "КП"},
        )

        manufacturer = self._last_manufacturer_name.strip() or None
        doc_extraction_id = self._last_document_extraction_id
        customer_org_id = getattr(self, "_last_customer_org_id", None)
        manufacturer_org_id = getattr(self, "_last_manufacturer_org_id", None)
        # Все tk-переменные — только main thread (иначе RuntimeError:
        # «main thread is not in main loop» → КП/заказ/пакет ломаются).
        style = (
            self.kp_style_var.get().strip()
            if hasattr(self, "kp_style_var")
            else None
        ) or None
        db_path = self.db_path
        from ...logging_setup import log_operator

        _log.info(
            "KP start style=%r manufacturer=%r extraction_id=%s "
            "customer_org=%s mfg_org=%s",
            style,
            (manufacturer or "")[:60],
            doc_extraction_id,
            customer_org_id,
            manufacturer_org_id,
            extra={"tag": "КП"},
        )
        log_operator(
            "KP start customer=%r manufacturer=%r calcs=%s out=%s",
            customer[:80],
            (manufacturer or "")[:60],
            ids,
            out_file.name,
            tag="КП",
        )

        from ..bg_job import run_bg_job

        def work() -> tuple[Path, int]:
            # pure: без tk / vars (D1)
            saved_path = generate_kp_from_db(
                customer=customer,
                subject=subject,
                calculation_ids=ids,
                output_path=out_file,
                db_path=db_path,
                note=note,
                style=style,
            )
            order_id = create_order_from_kp(
                customer_name=customer,
                manufacturer_name=manufacturer,
                customer_org_id=customer_org_id,
                manufacturer_org_id=manufacturer_org_id,
                subject=subject,
                note=note,
                calculation_ids=ids,
                kp_output_path=str(saved_path),
                document_extraction_id=doc_extraction_id,
                db_path=db_path,
            )
            return saved_path, order_id

        def on_ok(result: tuple[Path, int]) -> None:
            saved_path, order_id = result
            _log.info(
                "KP ok path=%s order_id=%s style=%r",
                saved_path,
                order_id,
                style,
                extra={"tag": "КП"},
            )
            self.status.set(f"Заказ №{order_id} · КП: {saved_path.name}")
            self._load_orders_table()
            # Авто-выбор заказа — сразу можно «Пакет документов»
            try:
                if hasattr(self, "orders_tree"):
                    iid = str(order_id)
                    if iid in self.orders_tree.get_children(""):
                        self.orders_tree.selection_set(iid)
                        self.orders_tree.see(iid)
                        self.orders_tree.focus(iid)
            except tk.TclError:
                pass
            try:
                import os

                os.startfile(str(saved_path))
            except OSError:
                pass
            messagebox.showinfo(
                "Заказ оформлен",
                f"Заказ №{order_id} сохранён.\n"
                f"КП открыт в Word:\n{saved_path}\n\n"
                "Далее: вкладка «Заказы» → выделите заказ → «Пакет документов».",
            )

        def on_err(exc: BaseException) -> None:
            messagebox.showerror(
                "Ошибка КП",
                f"{exc}\n\n"
                "Если ошибка про main loop / thread — перезапустите GUI "
                "после обновления.",
            )
            self.status.set("Ошибка формирования КП")

        run_bg_job(
            self,
            work,
            on_success=on_ok,
            on_error=on_err,
            name="generate_kp",
            tag="КП",
        )

    def _ask_document_pack_options(self, order_id: int) -> dict[str, str] | None:
        """Диалог: базовая папка + имя подпапки пакета."""
        pack_settings = get_document_pack_settings(self.db_path)
        default_base = pack_settings.base_dir.strip() or str(self.generated_dir)
        default_name = self._suggest_pack_folder_name(order_id)
        _log.info(
            "pack dialog open order_id=%s base=%r name=%r",
            order_id,
            default_base[:120],
            default_name,
            extra={"tag": "Пакет"},
        )

        # D4: create → widgets → run_modal (grab/geometry после pack)
        from ..modal import create_modal, run_modal

        dlg = create_modal(
            self,
            title=f"Пакет документов · заказ №{order_id}",
            minsize=(520, 280),
        )

        frame = ttk.Frame(dlg, padding=16, style="Card.TFrame")
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)

        base_var = tk.StringVar(master=dlg, value=default_base)
        name_var = tk.StringVar(master=dlg, value=default_name)

        ttk.Label(frame, text="Сохранить в папку:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        base_row = ttk.Frame(frame, style="Card.TFrame")
        base_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        base_row.columnconfigure(0, weight=1)
        base_entry = ttk.Entry(base_row, textvariable=base_var, width=48)
        base_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            base_row,
            text="Обзор…",
            command=lambda: self._browse_into_var(base_var, "Папка для пакета"),
        ).pack(side="left", padx=(6, 0))

        row_next = 2
        if pack_settings.recent_paths:
            ttk.Label(frame, text="Недавние пакеты:", style="CardMuted.TLabel").grid(
                row=row_next, column=0, sticky="w"
            )
            row_next += 1
            recent_var = tk.StringVar(master=dlg)
            recent_cb = ttk.Combobox(
                frame,
                textvariable=recent_var,
                values=pack_settings.recent_paths,
                width=54,
                state="readonly",
            )
            recent_cb.grid(row=row_next, column=0, sticky="ew", pady=(2, 10))
            row_next += 1

            def _use_recent(_e: object = None) -> None:
                p = recent_var.get().strip()
                if p:
                    base_var.set(str(Path(p).parent))

            recent_cb.bind("<<ComboboxSelected>>", _use_recent)

        ttk.Label(frame, text="Имя папки пакета:", style="Card.TLabel").grid(
            row=row_next, column=0, sticky="w", pady=(0, 4)
        )
        row_next += 1
        ttk.Entry(frame, textvariable=name_var, width=54).grid(
            row=row_next, column=0, sticky="ew", pady=(0, 16)
        )
        row_next += 1

        result: dict[str, str] = {}

        def _ok() -> None:
            base = base_var.get().strip()
            name = name_var.get().strip()
            if not base:
                messagebox.showwarning("Пакет", "Укажите базовую папку.", parent=dlg)
                return
            if not name:
                messagebox.showwarning("Пакет", "Укажите имя папки пакета.", parent=dlg)
                return
            try:
                Path(base).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(
                    "Пакет",
                    f"Не удалось создать/открыть папку:\n{base}\n\n{exc}",
                    parent=dlg,
                )
                return
            result["output_dir"] = base
            result["pack_folder_name"] = name
            _log.info(
                "pack dialog ok order_id=%s base=%r name=%r",
                order_id,
                base[:120],
                name,
                extra={"tag": "Пакет"},
            )
            dlg.destroy()

        def _cancel() -> None:
            _log.info("pack dialog cancelled order_id=%s", order_id, extra={"tag": "Пакет"})
            dlg.destroy()

        btns = ttk.Frame(frame, style="Card.TFrame")
        btns.grid(row=row_next, column=0, sticky="ew")
        self._accent_button(btns, "Собрать", _ok).pack(side="left")
        ttk.Button(btns, text="Отмена", command=_cancel).pack(side="left", padx=8)

        run_modal(dlg, prefer_w=560, prefer_h=320, focus=base_entry)
        return result or None

