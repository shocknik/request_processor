"""Mixin: PdfTabMixin — domain methods for Lab_request GUI."""

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
from ..state import (
    ORG_TYPE_LABELS,
    ORG_TYPE_VALUES,
    REQUEST_STATUS_UI,
    REQUEST_STEP_INDEX,
    CalcTestEntry,
    ExtractionDraft,
    RequestPageState,
)
from ..widgets.components import (
    BottomActionBar,
    EmptyState,
    PageHeader,
    StepIndicator,
    UploadPanel,
)
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

class PdfTabMixin:
    def _build_pdf_tab(self) -> None:
        """
        Страница «Заявки» (редизайн v0.10).

        Макет (сверху вниз):
          PageHeader → StepIndicator → UploadPanel → [OCR opts] → [warnings]
          → Paned(Марки | Организации+контекст) → BottomActionBar

        Бизнес-логика (extract/confirm/assistant) не дублируется — только UI.
        Состояние обновляется централизованно через ``render_request_state``.
        """
        root = self.tab_pdf
        # grid: header/steps/upload fixed; mid expands; bottom fixed
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)  # mid pane row (index after dynamic pack — use pack)

        # --- hidden path var (используется extract/browse) ---
        self.pdf_path_var = tk.StringVar()
        self.pdf_path_var.trace_add("write", lambda *_: self._on_pdf_path_changed())

        # --- Page header ---
        req_no = (getattr(self, "_last_document_extraction_id", None) or 0) + 1
        self.page_header = PageHeader(
            root,
            title=f"Новая заявка №{req_no}",
            subtitle="Загрузите документ, чтобы начать распознавание заявки.",
            status_text="Не обработана",
            status_tone="grey",
        )
        self.page_header.pack(fill="x", pady=(0, 10))

        # --- Steps (этапы заявки, не бизнес-разделы) ---
        self.step_indicator = StepIndicator(root)
        self.step_indicator.pack(fill="x", pady=(0, 12))

        # --- Upload ---
        self.upload_panel = UploadPanel(
            root,
            on_browse=self._browse_pdf,
            on_ocr_params=self._toggle_pdf_opts,
            on_drop_path=self._on_upload_drop_path,
        )
        self.upload_panel.pack(fill="x", pady=(0, 8))

        # OCR / флаги сохранения — свёрнуты; открываются «Параметры OCR»
        self.pdf_opts_frame = ttk.Frame(root, style="Card.TFrame", padding=8)
        opts = self.pdf_opts_frame
        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="OCR для сканов", variable=self.ocr_var, style="Card.TCheckbutton").pack(
            side="left"
        )
        self.ocr_pytorch_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts,
            text="torch-CV (эксперимент)",
            variable=self.ocr_pytorch_var,
            command=self._on_ocr_engine_toggle,
            style="Card.TCheckbutton",
        ).pack(side="left", padx=(10, 0))
        ttk.Label(opts, text="DPI:", style="CardMuted.TLabel").pack(side="left", padx=(12, 2))
        self.ocr_dpi_var = tk.IntVar(value=SCAN_OCR_DPI)
        self.ocr_dpi_combo = ttk.Combobox(
            opts,
            textvariable=self.ocr_dpi_var,
            values=(300, 400, 450, 500),
            width=5,
            state="readonly",
        )
        self.ocr_dpi_combo.pack(side="left")
        self.confirm_only_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts,
            text="Сохранять только после подтверждения",
            variable=self.confirm_only_var,
            command=self._on_confirm_only_toggle,
            style="Card.TCheckbutton",
        ).pack(side="left", padx=(8, 0))
        self.save_marks_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="Марки в БД сразу", variable=self.save_marks_var, style="Card.TCheckbutton"
        ).pack(side="left", padx=(12, 0))
        self.save_orgs_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts, text="Орг. в БД сразу", variable=self.save_orgs_var, style="Card.TCheckbutton"
        ).pack(side="left", padx=(8, 0))
        ttk.Button(opts, text="Текст…", command=self._run_extract_free_text).pack(side="right")

        # Предупреждения валидации (компактная полоса)
        self._warn_expanded = False
        self._warn_lines: list[str] = []
        self.validation_warn_frame = tk.Frame(root, bg=COLORS["warn_bg"], padx=8, pady=4)
        warn_header = tk.Frame(self.validation_warn_frame, bg=COLORS["warn_bg"])
        warn_header.pack(fill="x")
        self.validation_warn_summary_var = tk.StringVar(value="")
        tk.Label(
            warn_header,
            textvariable=self.validation_warn_summary_var,
            bg=COLORS["warn_bg"],
            fg=COLORS.get("warning_text", "#92400e"),
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self._warn_toggle_btn = tk.Button(
            warn_header,
            text="Подробнее",
            command=self._toggle_validation_warnings,
            bg=COLORS["warn_bg"],
            fg=COLORS.get("warning_text", "#92400e"),
            activebackground="#fde68a",
            activeforeground="#78350f",
            relief="flat",
            bd=0,
            padx=8,
            pady=2,
            font=("Segoe UI", 9, "underline"),
            cursor="hand2",
        )
        self._warn_toggle_btn.pack(side="right")
        self.validation_warn_detail = self._make_readonly_text(
            self.validation_warn_frame,
            height=4,
            wrap="word",
            font=("Segoe UI", 9),
            bg=COLORS["warn_bg"],
            fg=COLORS.get("warning_text", "#92400e"),
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.validation_warn_var = self.validation_warn_summary_var

        # --- Bottom action bar (pack bottom first so mid can expand) ---
        self.bottom_bar = BottomActionBar(
            root,
            on_snapshot=self._save_parse_snapshot,
            on_cancel=self._cancel_extraction_draft,
            on_primary=self._on_request_primary_action,
        )
        self.bottom_bar.pack_bar(side="bottom", fill="x", pady=(8, 0))

        # Back-compat aliases for confirm buttons (status bar / old code paths)
        self.confirm_btn = self.bottom_bar.primary_btn
        self.confirm_btn_top = None
        # validation strip (legacy color bar — keep for tests/status updates)
        self.validation_status_bar = tk.Frame(root, bg=COLORS["muted"], width=0, height=0)
        self.validation_status_var = tk.StringVar(value="Документ не обработан")

        # --- Mid: Марки (≈62%) | Организации (≈38%) ---
        mid = ttk.PanedWindow(root, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=(4, 0))
        self._pdf_mid_pane = mid

        # ---- Marks card ----
        left_border = tk.Frame(mid, bg=COLORS["border"], bd=0)
        left = tk.Frame(left_border, bg=COLORS["card"], padx=12, pady=12)
        left.pack(fill="both", expand=True, padx=1, pady=1)
        mid.add(left_border, weight=3)

        marks_header = tk.Frame(left, bg=COLORS["card"])
        marks_header.pack(fill="x", pady=(0, 8))
        tk.Label(
            marks_header,
            text="Марки",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 11),
        ).pack(side="left")

        mark_actions = tk.Frame(marks_header, bg=COLORS["card"])
        mark_actions.pack(side="right")
        self._btn_mark_add = ttk.Button(mark_actions, text="+ Добавить", command=self._add_draft_mark)
        self._btn_mark_add.pack(side="left", padx=(0, 4))
        self._btn_mark_edit = ttk.Button(
            mark_actions, text="Редактировать", command=self._edit_draft_mark
        )
        self._btn_mark_edit.pack(side="left", padx=(0, 4))
        self._btn_mark_del = ttk.Button(mark_actions, text="Удалить", command=self._remove_draft_mark)
        self._btn_mark_del.pack(side="left", padx=(0, 4))
        self._btn_mark_assistant = ttk.Button(
            mark_actions,
            text="Проверить ассистентом",
            style="Link.TButton",
            command=self._open_assistant_review_dialog,
        )
        self._btn_mark_assistant.pack(side="left", padx=(8, 0))

        # secondary row: accept/reject/toggle/to calc (не конкурируют с primary)
        mark_tb2 = tk.Frame(left, bg=COLORS["card"])
        mark_tb2.pack(fill="x", pady=(0, 6))
        ttk.Button(mark_tb2, text="Принять / отклонить", command=self._toggle_draft_mark).pack(
            side="left"
        )
        ttk.Button(mark_tb2, text="Принять подсказку", command=self._accept_assistant_for_selected).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(
            mark_tb2, text="Отклонить подсказку", command=self._reject_assistant_for_selected
        ).pack(side="left", padx=(4, 0))
        self._accent_button(mark_tb2, "→ В расчёт", self._use_mark_in_calc).pack(
            side="left", padx=(10, 0)
        )

        # Tree + empty state host
        self._marks_body = tk.Frame(left, bg=COLORS["card"])
        self._marks_body.pack(fill="both", expand=True)
        self._marks_body.rowconfigure(0, weight=1)
        self._marks_body.columnconfigure(0, weight=1)

        tree_wrap = ttk.Frame(self._marks_body, style="Card.TFrame")
        tree_wrap.grid(row=0, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        cols = (
            "status",
            "designation",
            "found_mark",
            "cores",
            "size",
            "document",
            "confidence",
        )
        self.marks_tree = ttk.Treeview(
            tree_wrap, columns=cols, show="headings", height=10, selectmode="browse"
        )
        for col, title, width, stretch in (
            ("status", "Статус", 110, False),
            ("designation", "Обозначение в документе", 220, True),
            ("found_mark", "Найденная марка", 120, True),
            ("cores", "ТПЖ", 48, False),
            ("size", "Размер", 72, False),
            ("document", "ТУ/ГОСТ", 140, True),
            ("confidence", "Уверенность", 100, False),
        ):
            self.marks_tree.heading(col, text=title)
            anchor = "center" if col in ("status", "cores", "confidence") else "w"
            self.marks_tree.column(
                col, width=width, anchor=anchor, stretch=stretch, minwidth=min(width, 48)
            )
        self.marks_tree.tag_configure("ok", background=COLORS["card"])
        self.marks_tree.tag_configure("warning", background=COLORS["warn_bg"])
        self.marks_tree.tag_configure("error", background=COLORS["error_bg"])
        self.marks_tree.tag_configure(
            "rejected", background="#f1f5f9", foreground=COLORS["muted"]
        )
        self.marks_tree.tag_configure("assist", background=COLORS["accent_light"])
        ysb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.marks_tree.yview)
        xsb = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.marks_tree.xview)
        self.marks_tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.marks_tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        self.marks_tree.bind("<<TreeviewSelect>>", self._on_draft_mark_select)
        self.marks_tree.bind("<Double-Button-1>", self._on_draft_mark_double_click)
        self.marks_tree.bind("<Return>", lambda _e: self._use_mark_in_calc())
        self._marks_tree_wrap = tree_wrap

        self.marks_empty = EmptyState(
            self._marks_body,
            title="Марки пока не извлечены",
            subtitle="После распознавания здесь появятся найденные марки.",
            icon_text="◇",
        )
        self.marks_empty.grid(row=0, column=0, sticky="nsew")
        self._show_marks_empty(True)

        # ---- Organizations card (scrollable + clipboard-friendly fields) ----
        right_border = tk.Frame(mid, bg=COLORS["border"], bd=0)
        right_shell = tk.Frame(right_border, bg=COLORS["card"])
        right_shell.pack(fill="both", expand=True, padx=1, pady=1)
        mid.add(right_border, weight=2)

        # Заголовок карточки — всегда виден
        tk.Label(
            right_shell,
            text="Организации",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 11),
        ).pack(anchor="w", padx=12, pady=(12, 4))

        # Прокручиваемая область: форма орг. + контекст марки
        scroll_host = tk.Frame(right_shell, bg=COLORS["card"])
        scroll_host.pack(fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        scroll_host.rowconfigure(0, weight=1)
        scroll_host.columnconfigure(0, weight=1)

        self._orgs_canvas = tk.Canvas(
            scroll_host,
            bg=COLORS["card"],
            highlightthickness=0,
            bd=0,
        )
        self._orgs_vsb = ttk.Scrollbar(
            scroll_host, orient="vertical", command=self._orgs_canvas.yview
        )
        self._orgs_canvas.configure(yscrollcommand=self._orgs_vsb.set)
        self._orgs_canvas.grid(row=0, column=0, sticky="nsew")
        self._orgs_vsb.grid(row=0, column=1, sticky="ns")

        org_inner = tk.Frame(self._orgs_canvas, bg=COLORS["card"], padx=8, pady=4)
        self._orgs_canvas_window = self._orgs_canvas.create_window(
            (0, 0), window=org_inner, anchor="nw"
        )
        self._orgs_scroll_inner = org_inner

        def _orgs_on_inner_configure(_event: tk.Event | None = None) -> None:
            # scrollregion по содержимому; полоса появляется, когда контент выше окна
            self._orgs_canvas.configure(scrollregion=self._orgs_canvas.bbox("all"))

        def _orgs_on_canvas_configure(event: tk.Event) -> None:
            self._orgs_canvas.itemconfigure(
                self._orgs_canvas_window, width=max(1, int(event.width))
            )

        org_inner.bind("<Configure>", _orgs_on_inner_configure)
        self._orgs_canvas.bind("<Configure>", _orgs_on_canvas_configure)

        # Колесо мыши — только когда курсор над областью организаций
        def _orgs_wheel(event: tk.Event) -> str | None:
            if not self._widget_is_under(event.widget, scroll_host):
                return None
            delta = int(getattr(event, "delta", 0) or 0)
            if delta == 0:
                return None
            steps = -1 if delta > 0 else 1
            self._orgs_canvas.yview_scroll(steps, "units")
            return "break"

        # bind_all не ставим — пересечётся с Настройками; bind на host + children
        self._orgs_canvas.bind("<MouseWheel>", _orgs_wheel)
        org_inner.bind("<MouseWheel>", _orgs_wheel)
        scroll_host.bind("<MouseWheel>", _orgs_wheel)

        org_form = tk.Frame(org_inner, bg=COLORS["card"])
        org_form.pack(fill="x")
        org_form.columnconfigure(0, weight=1)

        self.draft_customer_var = tk.StringVar()
        self.draft_customer_inn_var = tk.StringVar()
        self.draft_customer_addr_var = tk.StringVar()
        self.draft_manufacturer_var = tk.StringVar()
        self.draft_recipient_var = tk.StringVar()
        self.draft_customer_inn_var.trace_add("write", lambda *_: self._on_inn_changed())

        # tk.Entry (не только ttk): надёжный selection/copy/paste на Windows + ПКМ
        org_fields = (
            ("Заказчик", self.draft_customer_var, "entry"),
            ("ИНН", self.draft_customer_inn_var, "entry"),
            ("Адрес", self.draft_customer_addr_var, "text"),  # длинный — многострочный
            ("Производитель", self.draft_manufacturer_var, "entry"),
            ("Получатель (ИЛ)", self.draft_recipient_var, "entry"),
        )
        self._org_entries: dict[str, tk.Misc] = {}
        for row, (label, var, kind) in enumerate(org_fields):
            tk.Label(
                org_form,
                text=label,
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=("Segoe UI", 9),
                anchor="w",
            ).grid(row=row * 2, column=0, sticky="ew", pady=(6 if row else 0, 2))
            if kind == "text":
                # Адрес: 3 строки, своя прокрутка + Ctrl/C/V/X/A + ПКМ
                text_wrap = tk.Frame(org_form, bg=COLORS["border"], bd=0)
                text_wrap.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(0, 2))
                text_wrap.columnconfigure(0, weight=1)
                addr = tk.Text(
                    text_wrap,
                    height=3,
                    wrap="word",
                    font=("Segoe UI", 10),
                    bg=COLORS["card"],
                    fg=COLORS["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=COLORS["border"],
                    highlightcolor=COLORS["accent"],
                    insertbackground=COLORS["text"],
                    padx=6,
                    pady=4,
                )
                addr.grid(row=0, column=0, sticky="ew", padx=1, pady=1)
                # синхронизация Text ↔ StringVar
                self._bind_text_to_var(addr, var)
                self._enable_field_clipboard(addr)
                addr.bind("<MouseWheel>", _orgs_wheel, add="+")
                self._org_entries[label] = addr
            else:
                entry = tk.Entry(
                    org_form,
                    textvariable=var,
                    font=("Segoe UI", 10),
                    bg=COLORS["card"],
                    fg=COLORS["text"],
                    relief="solid",
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=COLORS["border"],
                    highlightcolor=COLORS["accent"],
                    insertbackground=COLORS["text"],
                )
                entry.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(0, 2), ipady=5)
                self._enable_field_clipboard(entry)
                entry.bind("<MouseWheel>", _orgs_wheel, add="+")
                self._org_entries[label] = entry

        # Контекст выбранной марки (внутри scroll)
        ctx_border = tk.Frame(org_inner, bg=COLORS["border"], bd=0)
        ctx_border.pack(fill="x", expand=False, pady=(12, 8))
        ctx = tk.Frame(ctx_border, bg=COLORS["info_bg"], padx=10, pady=10)
        ctx.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(
            ctx,
            text="Контекст выбранной марки",
            bg=COLORS["info_bg"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x")
        self._context_placeholder_var = tk.StringVar(
            value="Выберите марку в таблице, чтобы увидеть контекст распознавания."
        )
        self._context_placeholder = tk.Label(
            ctx,
            textvariable=self._context_placeholder_var,
            bg=COLORS["info_bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=280,
            justify="left",
            anchor="w",
        )
        self._context_placeholder.pack(fill="x", pady=(6, 0))
        self.mark_context_text = self._make_readonly_text(
            ctx,
            height=6,
            font=("Segoe UI", 9),
            bg=COLORS["info_bg"],
            relief="flat",
            highlightthickness=0,
        )
        # copy из контекста (readonly) — Ctrl+C / ПКМ
        self._enable_field_clipboard(self.mark_context_text, editable=False)
        self.mark_context_text.bind("<MouseWheel>", _orgs_wheel, add="+")
        self._context_host = ctx

        self._on_confirm_only_toggle()
        self._request_page_state = RequestPageState.EMPTY
        self._set_mark_action_buttons_enabled(False)
        self.render_request_state(RequestPageState.EMPTY)
        _log.info(
            "pdf_tab redesigned: header/steps/upload/marks/orgs(scroll+clipboard)/bar",
            extra={"tag": "UI"},
        )

    def _bind_text_to_var(self, widget: tk.Text, var: tk.StringVar) -> None:
        """Двусторонняя связь tk.Text ↔ StringVar (для Адреса и др.)."""

        def _from_var(*_args: object) -> None:
            new = var.get()
            cur = widget.get("1.0", "end-1c")
            if cur == new:
                return
            # не сбрасывать курсор при том же тексте
            try:
                widget.delete("1.0", "end")
                if new:
                    widget.insert("1.0", new)
            except tk.TclError:
                pass

        def _to_var(_event: tk.Event | None = None) -> None:
            try:
                text = widget.get("1.0", "end-1c")
            except tk.TclError:
                return
            if var.get() != text:
                var.set(text)

        var.trace_add("write", _from_var)
        widget.bind("<<Modified>>", lambda e: (_to_var(), widget.edit_modified(False)))
        widget.bind("<KeyRelease>", _to_var, add="+")
        widget.bind("<FocusOut>", _to_var, add="+")
        # начальное значение
        if var.get():
            widget.insert("1.0", var.get())
        _log.debug("Text↔StringVar bound for address-like field", extra={"tag": "UI"})

    def _enable_field_clipboard(
        self, widget: tk.Misc, *, editable: bool = True
    ) -> None:
        """
        Явные Ctrl+C/X/V/A, Shift+Ins и ПКМ-меню на поле.

        Дублирует class-bind ClipboardMixin: надёжнее на вложенных Frame/Canvas
        и при русской раскладке (keycode).
        """
        # Нативные события + наш handler (return "break" чтобы не дублировать вставку)
        widget.bind("<Control-c>", self._evt_copy, add="+")
        widget.bind("<Control-C>", self._evt_copy, add="+")
        widget.bind("<Control-v>", self._evt_paste if editable else self._evt_copy, add="+")
        widget.bind("<Control-V>", self._evt_paste if editable else self._evt_copy, add="+")
        widget.bind("<Control-x>", self._evt_cut if editable else self._evt_copy, add="+")
        widget.bind("<Control-X>", self._evt_cut if editable else self._evt_copy, add="+")
        widget.bind("<Control-a>", self._evt_select_all, add="+")
        widget.bind("<Control-A>", self._evt_select_all, add="+")
        widget.bind("<Control-KeyPress>", self._evt_ctrl_keycode, add="+")
        widget.bind("<Shift-Insert>", self._evt_paste if editable else (lambda e: "break"), add="+")
        widget.bind("<Control-Insert>", self._evt_copy, add="+")
        widget.bind("<Button-3>", self._evt_context_menu, add="+")
        # Помечаем для отладки
        try:
            widget._rp_clipboard = True  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Request page state machine (единая точка обновления UI)
    # ------------------------------------------------------------------

    def render_request_state(self, state: RequestPageState, **kwargs) -> None:
        """
        Централизованно обновить статус, этап, primary-кнопку, empty state, bottom bar.

        Не размещайте противоречивые set() status/buttons по разрозненным обработчикам —
        вызывайте этот метод (или тонкие обёртки, которые сводятся к нему).
        """
        self._request_page_state = state
        label, tone = REQUEST_STATUS_UI.get(state, ("Не обработана", "grey"))
        if hasattr(self, "page_header"):
            self.page_header.set_status(label, tone)
            step = REQUEST_STEP_INDEX.get(state, 0)
            if hasattr(self, "step_indicator"):
                self.step_indicator.set_step(step)

        # Подзаголовок
        subtitles = {
            RequestPageState.EMPTY: "Загрузите документ, чтобы начать распознавание заявки.",
            RequestPageState.FILE_SELECTED: "Документ выбран — нажмите «Извлечь данные».",
            RequestPageState.PROCESSING: "Идёт распознавание, пожалуйста, подождите…",
            RequestPageState.REVIEW_REQUIRED: "Проверьте марки и организации, затем подтвердите заявку.",
            RequestPageState.READY_TO_CONFIRM: "Данные готовы — можно подтвердить заявку.",
            RequestPageState.CONFIRMED: "Заявка подтверждена. Можно переходить к расчёту.",
            RequestPageState.ERROR: "Ошибка обработки. Исправьте файл или повторите извлечение.",
        }
        if hasattr(self, "page_header"):
            self.page_header.set_subtitle(subtitles.get(state, ""))

        # Primary button
        primary_map = {
            RequestPageState.EMPTY: ("Извлечь данные", False),
            RequestPageState.FILE_SELECTED: ("Извлечь данные", True),
            RequestPageState.PROCESSING: ("Распознавание…", False),
            RequestPageState.REVIEW_REQUIRED: ("Подтвердить заявку", True),
            RequestPageState.READY_TO_CONFIRM: ("Подтвердить заявку", True),
            RequestPageState.CONFIRMED: ("Извлечь данные", True),
            RequestPageState.ERROR: ("Извлечь данные", True),
        }
        text, enabled = primary_map.get(state, ("Извлечь данные", False))
        if kwargs.get("primary_enabled") is not None:
            enabled = bool(kwargs["primary_enabled"])
        if kwargs.get("primary_text"):
            text = str(kwargs["primary_text"])
        if hasattr(self, "bottom_bar"):
            self.bottom_bar.set_primary_text(text)
            self.bottom_bar.set_primary_enabled(enabled)
            self.bottom_bar.set_processing(state == RequestPageState.PROCESSING)

        # Title number
        if hasattr(self, "page_header") and state == RequestPageState.EMPTY:
            req_no = (getattr(self, "_last_document_extraction_id", None) or 0) + 1
            self.page_header.set_title(f"Новая заявка №{req_no}")

        _log.info(
            "render_request_state state=%s primary=%r enabled=%s",
            state.value,
            text,
            enabled,
            extra={"tag": "UI"},
        )

    def _on_request_primary_action(self) -> None:
        """Единственная главная кнопка: extract или confirm в зависимости от state."""
        state = getattr(self, "_request_page_state", RequestPageState.EMPTY)
        _log.info("primary action state=%s", getattr(state, "value", state), extra={"tag": "Заявка"})
        if state in (
            RequestPageState.REVIEW_REQUIRED,
            RequestPageState.READY_TO_CONFIRM,
        ):
            self._confirm_extraction()
            return
        # EMPTY / FILE / ERROR / CONFIRMED / PROCESSING → extract (PROCESSING disabled)
        self._run_extract_pdf()

    def _on_pdf_path_changed(self) -> None:
        """Реакция на смену пути файла (browse / drop / programmatic)."""
        path = (self.pdf_path_var.get() or "").strip()
        if not path:
            if hasattr(self, "upload_panel"):
                self.upload_panel.set_empty()
            if hasattr(self, "bottom_bar"):
                self.bottom_bar.set_doc_status("Документ не выбран")
            if not self._extraction_draft:
                self.render_request_state(RequestPageState.EMPTY)
            return
        p = Path(path)
        size_label = ""
        try:
            if p.is_file():
                size_b = p.stat().st_size
                if size_b < 1024:
                    size_label = f"{size_b} Б"
                elif size_b < 1024 * 1024:
                    size_label = f"{size_b / 1024:.1f} КБ"
                else:
                    size_label = f"{size_b / (1024 * 1024):.1f} МБ"
        except OSError:
            pass
        kind = p.suffix.upper().lstrip(".") or "файл"
        if hasattr(self, "upload_panel"):
            self.upload_panel.set_file(p.name, size_label=size_label, kind=kind)
        if hasattr(self, "bottom_bar"):
            doc = f"{p.name}" + (f" · {size_label}" if size_label else "")
            self.bottom_bar.set_doc_status(doc)
        # Не затирать draft/processing/confirmed, если уже есть результат
        cur = getattr(self, "_request_page_state", RequestPageState.EMPTY)
        if cur in (
            RequestPageState.EMPTY,
            RequestPageState.FILE_SELECTED,
            RequestPageState.ERROR,
            RequestPageState.CONFIRMED,
        ):
            self.render_request_state(RequestPageState.FILE_SELECTED)

    def _on_upload_drop_path(self, path: str) -> None:
        """Drop файла в UploadPanel."""
        if path:
            self.pdf_path_var.set(path)
            _log.info("drop file=%s", path, extra={"tag": "Заявка"})

    def _on_inn_changed(self) -> None:
        """Визуальная проверка ИНН (длина 10/12, только цифры) — без смены бизнес-валидации."""
        entry = self._org_entries.get("ИНН")
        if entry is None:
            return
        raw = (self.draft_customer_inn_var.get() or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        ok = (not raw) or (raw == digits and len(digits) in (10, 12))
        try:
            # tk.Entry: подсветка рамкой (highlight*)
            if ok:
                entry.configure(
                    highlightbackground=COLORS["border"],
                    highlightcolor=COLORS["accent"],
                    bg=COLORS["card"],
                )
            else:
                entry.configure(
                    highlightbackground=COLORS.get("error", "#DC2626"),
                    highlightcolor=COLORS.get("error", "#DC2626"),
                    bg=COLORS.get("error_bg", "#FEF2F2"),
                )
        except tk.TclError:
            pass
        if raw and not ok:
            _log.debug("INN visual invalid len=%s", len(raw), extra={"tag": "UI"})

    def _show_marks_empty(self, show: bool) -> None:
        """Переключить EmptyState / Treeview для карточки марок."""
        if not hasattr(self, "marks_empty"):
            return
        if show:
            self.marks_empty.lift()
            self._marks_tree_wrap.lower()
        else:
            self._marks_tree_wrap.lift()
            self.marks_empty.lower()

    def _set_mark_action_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for name in (
            "_btn_mark_edit",
            "_btn_mark_del",
        ):
            btn = getattr(self, name, None)
            if btn is not None:
                try:
                    btn.configure(state=state)
                except tk.TclError:
                    pass

    def _normalize_mark_lookup(self, mark: str) -> str:
        text = mark.replace("×", "x").replace("Х", "x").replace("х", "x")
        return re.sub(r"\s+", " ", text.strip().lower())

    def _find_mark_validation(self, mark: str) -> MarkValidation | None:
        if not self._extraction_draft or not mark.strip():
            return None
        key = self._normalize_mark_lookup(mark)
        for entry in self._extraction_draft.marks:
            if not entry.accepted:
                continue
            if self._normalize_mark_lookup(entry.mark) == key:
                return entry
            if key in self._normalize_mark_lookup(entry.mark):
                return entry
        return None

    def _suggested_test_codes_for_mark(self, mark: str) -> list[str]:
        entry = self._find_mark_validation(mark)
        if entry and entry.suggested_tests:
            return list(entry.suggested_tests)
        if entry and entry.requirements_raw:
            suggestions = map_requirements_to_tests(
                entry.requirements_raw,
                db_path=self.db_path,
            )
            return [s.code for s in suggestions]
        return []

    def _apply_suggested_tests_from_application(self) -> None:
        mark = self.mark_var.get().strip()
        if not mark:
            messagebox.showwarning(
                "Расчёт",
                "Укажите марку кабеля или подставьте её с вкладки «1. Заявка» (→ В расчёт).",
            )
            return

        entry = self._find_mark_validation(mark)
        if entry and entry.requirements_raw:
            suggestions = map_requirements_to_tests(
                entry.requirements_raw,
                db_path=self.db_path,
            )
            codes = [s.code for s in suggestions]
            for s in suggestions:
                if s.source == "database" and s.mapping_id:
                    record_mapping_usage(s.mapping_id, self.db_path)
        else:
            codes = self._suggested_test_codes_for_mark(mark)
            suggestions = []

        if not codes:
            messagebox.showinfo(
                "Испытания из заявки",
                "Для этой марки нет текста требований.\n\n"
                "Извлеките направление в ИЛ (table-first) и подтвердите заявку, "
                "либо выберите марку из таблицы на вкладке «1. Заявка».",
            )
            return

        existing = {e.code for e in self._calc_entries}
        added = 0
        for code in codes:
            if code not in existing:
                self._add_test_to_calc(code)
                existing.add(code)
                added += 1

        names = [
            self._tests_by_code.get(c, {}).get("name", c)[:40]
            for c in codes
            if c in self._tests_by_code
        ]
        if added:
            self.status.set(f"Добавлено испытаний из заявки: {added}")
            messagebox.showinfo(
                "Испытания из заявки",
                f"Добавлено: {added}\n"
                + "\n".join(f"  • {n}" for n in names[:8])
                + (f"\n  … и ещё {len(names) - 8}" if len(names) > 8 else ""),
            )
        else:
            messagebox.showinfo(
                "Испытания из заявки",
                "Все предложенные испытания уже в списке расчёта.",
            )
        self._update_calc_suggestions_hint()
        self._refresh_calc_picker()

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
        validation_state: str = "",
    ) -> str:
        parts = [
            f"📄 {file_name}",
            source_type.upper(),
        ]
        if page_count:
            parts.append(f"{page_count} стр.")
        parts.append(f"{marks_count} марок")
        if validation_state == "draft":
            parts.append("⚠ черновик")
        elif validation_state == "confirmed":
            parts.append("✓ подтверждено")
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

    def _on_confirm_only_toggle(self) -> None:
        if self.confirm_only_var.get():
            self.save_marks_var.set(False)
            self.save_orgs_var.set(False)

    @staticmethod
    def _status_icon(status: FieldStatus) -> str:
        return {"ok": "✓", "warning": "⚠", "error": "✗"}[status.value]

    def _mark_tree_tag(self, mark: MarkValidation, *, has_hint: bool = False) -> str:
        if not mark.accepted:
            return "rejected"
        if has_hint:
            return "assist"
        return mark.status.value

    def _rebuild_assistant_hints(self) -> None:
        """Пересчитывает кэш подсказок 💡 для текущего черновика."""
        self._assistant_hints = {}
        if not self._extraction_draft:
            return
        from ...assistant.mark_corrector import get_mark_corrector
        corrector = get_mark_corrector(self.db_path)
        ctx = AssistantContext(
            document_text=self._extraction_draft.result.text[:4000]
            if self._extraction_draft.result.text
            else None,
            document_type=self._extraction_draft.result.source_type,
        )
        for idx, mark in enumerate(self._extraction_draft.marks):
            try:
                suggestion = corrector.suggest(mark.mark, context=ctx)
            except Exception:  # noqa: BLE001
                continue
            if suggestion.changed:
                self._assistant_hints[idx] = suggestion.suggested

    def _mark_status_label(self, mark: MarkValidation, *, idx: int = -1) -> str:
        """
        Понятный статус строки (не одиночный символ).

        Не проверено | Принято | Исправлено | Отклонено | Не найдено
        """
        if not mark.accepted:
            return "Отклонено"
        if mark.status == FieldStatus.error:
            return "Не найдено"
        # Исправлено: отличается от исходного OCR-варианта
        if self._extraction_draft and 0 <= idx < len(self._extraction_draft.original_marks):
            original = self._extraction_draft.original_marks[idx]
            if (original.mark or "").strip() != (mark.mark or "").strip():
                return "Исправлено"
        if mark.status == FieldStatus.warning:
            return "Не проверено"
        return "Принято"

    def _confidence_label(self, confidence: float) -> str:
        """Процент + категория Высокая/Средняя/Низкая."""
        pct = f"{confidence:.0%}"
        if confidence >= 0.8:
            cat = "Высокая"
        elif confidence >= 0.5:
            cat = "Средняя"
        else:
            cat = "Низкая"
        return f"{pct} · {cat}"

    def _refresh_marks_tree(self) -> None:
        if not hasattr(self, "marks_tree"):
            return
        for item in self.marks_tree.get_children():
            self.marks_tree.delete(item)
        if not self._extraction_draft:
            self._assistant_hints = {}
            self._show_marks_empty(True)
            self._set_mark_action_buttons_enabled(False)
            return
        # лёгкий rebuild подсказок (детерминированный, быстрый)
        self._rebuild_assistant_hints()
        marks = self._extraction_draft.marks
        self._show_marks_empty(len(marks) == 0)
        for idx, mark in enumerate(marks):
            doc = mark.document or ""
            size_text = ""
            if mark.characteristic_size is not None:
                unit = "мм²" if mark.size_unit == "mm2" else "мм"
                size_text = f"{mark.characteristic_size:g}{unit}"
            has_hint = idx in self._assistant_hints
            found = mark.brand or ""
            if has_hint and self._assistant_hints.get(idx):
                # найденная / предложенная нормализация
                found = found or self._assistant_hints[idx]
            self.marks_tree.insert(
                "",
                "end",
                iid=str(idx),
                tags=(self._mark_tree_tag(mark, has_hint=has_hint),),
                values=(
                    self._mark_status_label(mark, idx=idx),
                    mark.mark,
                    found,
                    str(mark.cores_count or ""),
                    size_text,
                    doc,
                    self._confidence_label(mark.confidence),
                ),
            )
        self._set_mark_action_buttons_enabled(False)
        _log.debug(
            "marks_tree refreshed n=%s",
            len(marks),
            extra={"tag": "Заявка"},
        )

    def _toggle_validation_warnings(self) -> None:
        """Развернуть/свернуть длинный список предупреждений (не съедает mid)."""
        if not self._warn_lines:
            return
        self._warn_expanded = not self._warn_expanded
        self._render_validation_warnings_ui()

    def _render_validation_warnings_ui(self) -> None:
        """Компактная полоса + опционально ScrolledText (max ~4 строки)."""
        if not self._warn_lines:
            self.validation_warn_frame.pack_forget()
            self.validation_warn_detail.pack_forget()
            return

        n = len(self._warn_lines)
        first = self._warn_lines[0]
        if len(first) > 100:
            first = first[:97] + "…"
        summary = f"⚠ {n} предупр." + (f" — {first}" if n else "")
        if n > 1 and not self._warn_expanded:
            summary += f"  (+{n - 1})"
        self.validation_warn_summary_var.set(summary)
        self._warn_toggle_btn.configure(
            text="Свернуть" if self._warn_expanded else "Подробнее"
        )

        # Между upload/opts и mid: pack с before=mid
        mid = getattr(self, "_pdf_mid_pane", None)
        if mid is not None and mid.winfo_manager():
            self.validation_warn_frame.pack(
                fill="x", pady=(0, 4), before=mid
            )
        elif getattr(self, "pdf_opts_frame", None) is not None and self.pdf_opts_frame.winfo_manager():
            self.validation_warn_frame.pack(
                fill="x", pady=(0, 4), after=self.pdf_opts_frame
            )
        else:
            self.validation_warn_frame.pack(fill="x", pady=(0, 4))

        if self._warn_expanded:
            detail = "\n".join(f"• {line}" for line in self._warn_lines)
            self.validation_warn_detail.configure(state="normal")
            self.validation_warn_detail.delete("1.0", "end")
            self.validation_warn_detail.insert("1.0", detail)
            if not getattr(self.validation_warn_detail, "_rp_readonly", False):
                self.validation_warn_detail.configure(state="disabled")
            # height fixed: не более 4–5 видимых строк + внутренний scroll
            lines_show = min(5, max(3, min(n, 5)))
            self.validation_warn_detail.configure(height=lines_show)
            self.validation_warn_detail.pack(fill="x", pady=(4, 0))
        else:
            self.validation_warn_detail.pack_forget()

    def _update_validation_warnings(self, report: ValidationReport) -> None:
        lines: list[str] = []
        if report.flags:
            lines.extend(str(flag) for flag in report.flags)
        for mark in report.marks:
            for warning in mark.warnings:
                short = (
                    f"Марка «{mark.mark[:40]}…»: {warning}"
                    if len(mark.mark) > 40
                    else f"Марка «{mark.mark}»: {warning}"
                )
                if short not in lines:
                    lines.append(short)
        self._warn_lines = lines
        # По умолчанию свёрнуто — таблица марок остаётся на экране
        self._warn_expanded = False
        if lines:
            self._render_validation_warnings_ui()
        else:
            self.validation_warn_summary_var.set("")
            self.validation_warn_frame.pack_forget()
            self.validation_warn_detail.pack_forget()

    def _set_confirm_buttons_state(self, state: str) -> None:
        """Back-compat: включает/выключает primary (confirm) в bottom bar."""
        enabled = state == "normal"
        bar = getattr(self, "bottom_bar", None)
        if bar is not None:
            # При draft primary = «Подтвердить»; при idle — extract disabled отдельно
            bar.set_primary_enabled(enabled)
        for btn in (getattr(self, "confirm_btn", None), getattr(self, "confirm_btn_top", None)):
            if btn is not None and btn is not getattr(bar, "primary_btn", None):
                self._set_button_enabled(btn, enabled)

    def _update_validation_status_bar(
        self,
        *,
        state: str,
        file_name: str = "",
        result: PdfExtractionResult | None = None,
        report: ValidationReport | None = None,
    ) -> None:
        """
        Legacy-хук (idle/draft/confirmed/error) → RequestPageState.

        Сохраняет validation_status_var для совместимости; UI-статус идёт через
        render_request_state / page_header badge.
        """
        colors = {
            "idle": COLORS["muted"],
            "draft": COLORS["draft_accent"],
            "confirmed": COLORS["confirmed_accent"],
            "error": COLORS.get("error", "#dc2626"),
        }
        try:
            self.validation_status_bar.configure(bg=colors.get(state, COLORS["muted"]))
        except tk.TclError:
            pass

        if state == "idle":
            self.validation_status_var.set(
                "Документ не обработан — выберите файл и нажмите «Извлечь данные»"
            )
            if not (self.pdf_path_var.get() or "").strip():
                self.render_request_state(RequestPageState.EMPTY)
            else:
                self.render_request_state(RequestPageState.FILE_SELECTED)
            return

        if state == "error":
            self.validation_status_var.set("Ошибка извлечения — повторите «Извлечь данные»")
            self.render_request_state(RequestPageState.ERROR)
            return

        parts: list[str] = []
        if state == "draft":
            parts.append("ЧЕРНОВИК")
        elif state == "confirmed":
            parts.append("ПОДТВЕРЖДЕНО")

        if file_name:
            parts.append(file_name)
        if result:
            parts.append(result.source_type.upper())
            if result.page_count:
                parts.append(f"{result.page_count} стр.")
            if result.ocr_used:
                eng = result.ocr_engine or "ocr"
                if eng == "easyocr":
                    parts.append("OCR·torch-CV")
                else:
                    parts.append(f"OCR·{eng}")
        if report:
            accepted = (
                sum(1 for m in self._extraction_draft.marks if m.accepted)
                if self._extraction_draft
                else 0
            )
            parts.append(f"{accepted} марок")
            parts.append(f"уверенность {report.overall_confidence:.0%}")
            if report.document_type != "unknown":
                parts.append(report.document_type)

        self.validation_status_var.set("  ·  ".join(parts))

        if state == "draft" and report:
            needs_review = bool(report.flags) or any(
                m.status != FieldStatus.ok for m in (self._extraction_draft.marks if self._extraction_draft else [])
            )
            page_state = (
                RequestPageState.REVIEW_REQUIRED
                if needs_review
                else RequestPageState.READY_TO_CONFIRM
            )
            # block_confirm → primary disabled, но state всё равно review
            self.render_request_state(
                page_state,
                primary_enabled=not report.block_confirm,
            )
            if file_name and hasattr(self, "page_header"):
                self.page_header.set_title(f"Заявка · {file_name}")
        elif state == "confirmed":
            self.render_request_state(RequestPageState.CONFIRMED)
            if file_name and hasattr(self, "page_header"):
                self.page_header.set_title(f"Заявка · {file_name}")

    def _show_extraction_draft(self, draft: ExtractionDraft) -> None:
        self._extraction_draft = draft
        self._extraction_confirmed = False
        self._refresh_marks_tree()
        self._fill_draft_org_fields(draft)
        self._apply_test_type_from_document(draft.result.text)
        self._update_validation_warnings(draft.report)
        self._show_context_placeholder(True)
        self._set_text(self.mark_context_text, "")
        # Синхронизируем path (free-text / extract)
        try:
            if draft.source_path and str(draft.source_path) not in ("", "."):
                self.pdf_path_var.set(str(draft.source_path))
        except Exception:  # noqa: BLE001
            pass
        self._update_validation_status_bar(
            state="draft",
            file_name=Path(draft.source_path).name,
            result=draft.result,
            report=draft.report,
        )
        self.parse_info_var.set(
            self._format_parse_info(
                file_name=Path(draft.source_path).name,
                source_type=draft.result.source_type,
                marks_count=sum(1 for m in draft.marks if m.accepted),
                customer_name=draft.report.customer_name,
                manufacturer_name=draft.report.manufacturer_name,
                ocr_used=draft.result.ocr_used,
                page_count=draft.result.page_count,
                extracted_at=draft.result.extracted_at.isoformat(),
                validation_state="draft",
            )
        )

    def _ensure_assistant_session(self) -> str:
        if not self._extraction_draft:
            return datetime.now().strftime("%Y%m%d%H%M%S")
        if not self._extraction_draft.assistant_session_id:
            self._extraction_draft.assistant_session_id = datetime.now().strftime(
                "%Y%m%d%H%M%S"
            )
        return self._extraction_draft.assistant_session_id

    def _doc_name_for_assistant(self) -> str:
        if not self._extraction_draft:
            return ""
        return Path(self._extraction_draft.source_path).name

    def _apply_mark_suggestion_to_draft(
        self,
        idx: int,
        suggested: str,
        *,
        suggestion_meta: dict | None = None,
    ) -> bool:
        """Применяет suggested к марке idx; True если изменилось."""
        if not self._extraction_draft or not (0 <= idx < len(self._extraction_draft.marks)):
            return False
        mark = self._extraction_draft.marks[idx]
        if mark.mark.strip() == suggested.strip():
            return False
        new_mark = mark.model_copy(update={"mark": suggested})
        try:
            parsed = parse_cable_mark_record(suggested, document=mark.document)
            new_mark = new_mark.model_copy(
                update={
                    "brand": parsed.brand or mark.brand,
                    "cores_count": parsed.cores_count or mark.cores_count,
                    "characteristic_size": (
                        parsed.characteristic_size
                        if parsed.characteristic_size is not None
                        else mark.characteristic_size
                    ),
                    "size_unit": parsed.size_unit or mark.size_unit,
                    "fire_class": parsed.fire_class or mark.fire_class,
                    "document": parsed.document or mark.document,
                }
            )
        except Exception:  # noqa: BLE001
            pass
        self._extraction_draft.marks[idx] = new_mark
        meta = suggestion_meta or {}
        _log.info(
            "assistant accept raw=%r suggested=%r conf=%s source=%s",
            mark.mark,
            suggested,
            meta.get("confidence"),
            meta.get("source"),
        )
        return True

    def _record_assistant_decision(
        self,
        *,
        decision: str,
        raw: str,
        suggested: str,
        confidence: float = 0.0,
        source: str = "deterministic",
        reason: str = "",
        mark_index: int | None = None,
        flush: bool = False,
    ) -> None:
        if not self._extraction_draft:
            return
        event = AssistantFeedbackEvent(
            decision=decision,  # type: ignore[arg-type]
            raw=raw,
            suggested=suggested,
            confidence=confidence,
            source=source,
            reason=reason,
            document=self._doc_name_for_assistant(),
            mark_index=mark_index,
            session_id=self._ensure_assistant_session(),
        )
        self._extraction_draft.assistant_events.append(event)
        if flush:
            append_assistant_feedback(
                [event],
                db_path=self.db_path,
            )

    def _format_mark_context_panel(self, mark: MarkValidation) -> str:
        """Показывает нормализованную марку, а не сырой OCR-мусор."""
        lines = [f"Марка: {mark.mark}"]
        if mark.document:
            lines.append(f"ТУ/ГОСТ: {mark.document}")
        try:
            from ...assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
            suggestion = suggest_mark_correction(mark.mark, db_path=self.db_path)
            if suggestion.changed:
                lines.append(
                    f"\nАссистент 💡: «{suggestion.suggested}» "
                    f"({suggestion.confidence:.0%}, {suggestion.source})"
                )
                if suggestion.reason:
                    lines.append(f"  {suggestion.reason}")
                lines.append("  → «Принять 💡» / «Отклонить 💡» или диалог «Ассистент»")
            else:
                lines.append("\nАссистент: без правок")
            from ...assistant.mark_corrector import get_mark_corrector
            alts = get_mark_corrector(self.db_path).candidates(mark.mark, limit=3)
            if alts and (not suggestion.changed or alts[0][0] != suggestion.suggested):
                lines.append("  Похожие в БД:")
                for cand, score in alts[:3]:
                    lines.append(f"    · {cand} ({score:.0%})")
        except Exception as exc:  # noqa: BLE001 — UI не должен падать
            lines.append(f"\nАссистент недоступен: {exc}")

        tests = list(mark.suggested_tests or [])
        if not tests and mark.requirements_raw:
            try:
                tests = [
                    s.code
                    for s in map_requirements_to_tests(
                        mark.requirements_raw, db_path=self.db_path
                    )
                ]
            except Exception:  # noqa: BLE001
                tests = []
        if tests:
            lines.append(f"\nИспытания из заявки: {', '.join(tests)}")
            lines.append("  (вкладка «2. Расчёт» → «Испытания из заявки»)")
        elif mark.requirements_raw:
            lines.append(f"\nТребования (сырьё):\n{mark.requirements_raw[:240]}")

        raw = (mark.context or "").strip()
        if not raw:
            lines.append("\n(фрагмент документа не сохранён)")
            return "\n".join(lines)
        probe = re.sub(r"\s+", "", mark.mark.lower())[:24]
        blob = re.sub(r"\s+", " ", raw)
        pos = blob.lower().find(probe[:16]) if probe else -1
        if pos < 0:
            pos = blob.lower().find(mark.mark[:12].lower())
        if pos >= 0:
            left = max(0, pos - 60)
            right = min(len(blob), pos + len(mark.mark) + 80)
            snippet = blob[left:right].strip()
            if left > 0:
                snippet = "…" + snippet
            if right < len(blob):
                snippet += "…"
            lines.append(f"\nФрагмент в документе:\n{snippet}")
        else:
            lines.append(f"\nФрагмент в документе:\n{blob[:280]}…")
        return "\n".join(lines)

    def _accept_assistant_for_selected(self) -> None:
        """Принять подсказку для выделенной марки."""
        if not self._extraction_draft:
            messagebox.showinfo("Ассистент", "Сначала извлеките заявку.")
            return
        sel = self.marks_tree.selection()
        if not sel:
            messagebox.showinfo("Ассистент", "Выберите марку с 💡 в таблице.")
            return
        idx = int(sel[0])
        from ...assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
        suggestion = suggest_mark_correction(
            self._extraction_draft.marks[idx].mark, db_path=self.db_path
        )
        if not suggestion.changed:
            messagebox.showinfo("Ассистент", "Для этой марки подсказки нет.")
            return
        raw = self._extraction_draft.marks[idx].mark
        self._apply_mark_suggestion_to_draft(
            idx,
            suggestion.suggested,
            suggestion_meta={
                "confidence": suggestion.confidence,
                "source": suggestion.source,
            },
        )
        self._record_assistant_decision(
            decision="accepted",
            raw=raw,
            suggested=suggestion.suggested,
            confidence=suggestion.confidence,
            source=suggestion.source,
            reason=suggestion.reason,
            mark_index=idx,
            flush=True,
        )
        self._revalidate_draft()
        self.status.set(f"Принято: {raw[:40]} → {suggestion.suggested[:40]}")

    def _reject_assistant_for_selected(self) -> None:
        """Отклонить подсказку (марка остаётся, событие в журнал)."""
        if not self._extraction_draft:
            return
        sel = self.marks_tree.selection()
        if not sel:
            messagebox.showinfo("Ассистент", "Выберите марку с 💡.")
            return
        idx = int(sel[0])
        mark = self._extraction_draft.marks[idx]
        from ...assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
        suggestion = suggest_mark_correction(mark.mark, db_path=self.db_path)
        if not suggestion.changed:
            messagebox.showinfo("Ассистент", "Подсказки нет — отклонять нечего.")
            return
        self._record_assistant_decision(
            decision="rejected",
            raw=mark.mark,
            suggested=suggestion.suggested,
            confidence=suggestion.confidence,
            source=suggestion.source,
            reason=suggestion.reason,
            mark_index=idx,
            flush=True,
        )
        # Убираем 💡 из кэша, чтобы не навязывать снова в этой сессии
        self._assistant_hints.pop(idx, None)
        self._refresh_marks_tree()
        self.status.set(f"Отклонено: {suggestion.suggested[:50]}")

    def _open_assistant_review_dialog(self) -> None:
        """Диалог ассистента: подсказки или понятный статус «всё ок»."""
        if not self._extraction_draft:
            messagebox.showinfo("Ассистент", "Сначала извлеките заявку (файл или текст).")
            return

        from ...assistant.mark_corrector import get_mark_corrector
        corrector = get_mark_corrector(self.db_path)
        items: list[tuple[int, str, object]] = []
        checked = 0
        for idx, mark in enumerate(self._extraction_draft.marks):
            if not mark.accepted:
                continue
            checked += 1
            s = corrector.suggest(mark.mark)
            if s.changed:
                items.append((idx, mark.mark, s))

        if not items:
            messagebox.showinfo(
                "Ассистент — всё в порядке",
                "Проверено марок: {n}.\n"
                "Дополнительных правок нет.\n\n"
                "Как это работает:\n"
                "• При извлечении OCR-марки уже чуть нормализуются "
                "(KCBur→КСБнг, латиница→кириллица).\n"
                "• Ассистент ищет, что ещё можно улучшить (fuzzy к базе марок).\n"
                "• Если в таблице есть 💡 — есть конкретная подсказка: "
                "«Принять» / «Отклонить» или снова «Ассистент 💡».\n"
                "• Ручная правка: выделите строку → «Изменить» "
                "(или двойной клик) → «Сохранить в заявку».\n\n"
                "«Уже в базе» ≠ ошибка: значит текущие обозначения "
                "совпадают с эталоном / правилами.".format(n=checked),
            )
            self.status.set(f"Ассистент: {checked} марок без доп. правок")
            return

        dialog = tk.Toplevel(self)
        dialog.title(f"Ассистент — {len(items)} подсказок")
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(bg=COLORS["bg"])

        ttk.Label(
            dialog,
            text=(
                f"Найдено {len(items)} из {checked} марок с предложением правки.\n"
                "✓ = применить при «Применить выбранные». Двойной клик / пробел — снять галочку."
            ),
            style="Muted.TLabel",
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 4))

        cols = ("use", "raw", "suggested", "conf", "source", "reason")
        tree = ttk.Treeview(dialog, columns=cols, show="headings", height=12, selectmode="browse")
        for col, title, w in (
            ("use", "✓", 36),
            ("raw", "Сейчас", 200),
            ("suggested", "Подсказка", 200),
            ("conf", "%", 48),
            ("source", "Источник", 90),
            ("reason", "Почему", 180),
        ):
            tree.heading(col, text=title)
            tree.column(col, width=w, anchor="center" if col in ("use", "conf") else "w")
        tree.pack(fill="both", expand=True, padx=12, pady=4)

        row_state: dict[str, bool] = {}
        for idx, raw, s in items:
            iid = str(idx)
            row_state[iid] = True
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    "✓",
                    raw,
                    s.suggested,
                    f"{s.confidence:.0%}",
                    s.source,
                    (s.reason or "")[:80],
                ),
            )

        def toggle_row(_event=None) -> str:
            sel = tree.selection()
            if not sel:
                return "break"
            iid = sel[0]
            row_state[iid] = not row_state.get(iid, True)
            vals = list(tree.item(iid, "values"))
            vals[0] = "✓" if row_state[iid] else "—"
            tree.item(iid, values=vals)
            return "break"

        tree.bind("<Double-Button-1>", toggle_row)
        tree.bind("<space>", toggle_row)

        meta_by_idx = {str(idx): s for idx, _raw, s in items}

        def apply_choices() -> None:
            accepted_n = 0
            rejected_n = 0
            events: list[AssistantFeedbackEvent] = []
            session = self._ensure_assistant_session()
            doc = self._doc_name_for_assistant()
            for iid, use in row_state.items():
                idx = int(iid)
                s = meta_by_idx[iid]
                raw = (
                    self._extraction_draft.marks[idx].mark
                    if self._extraction_draft
                    else ""
                )
                if use:
                    if self._apply_mark_suggestion_to_draft(
                        idx,
                        s.suggested,
                        suggestion_meta={
                            "confidence": s.confidence,
                            "source": s.source,
                        },
                    ):
                        accepted_n += 1
                    events.append(
                        AssistantFeedbackEvent(
                            decision="accepted",
                            raw=raw,
                            suggested=s.suggested,
                            confidence=s.confidence,
                            source=s.source,
                            reason=s.reason,
                            document=doc,
                            mark_index=idx,
                            session_id=session,
                        )
                    )
                else:
                    rejected_n += 1
                    events.append(
                        AssistantFeedbackEvent(
                            decision="rejected",
                            raw=raw,
                            suggested=s.suggested,
                            confidence=s.confidence,
                            source=s.source,
                            reason=s.reason,
                            document=doc,
                            mark_index=idx,
                            session_id=session,
                        )
                    )
            if self._extraction_draft:
                self._extraction_draft.assistant_events.extend(events)
            path = append_assistant_feedback(events, db_path=self.db_path)
            self._revalidate_draft()
            dialog.destroy()
            self.status.set(
                f"Ассистент: принято {accepted_n}, отклонено {rejected_n}"
                + (f" · {path.name}" if path else "")
            )

        def accept_all() -> None:
            for iid in row_state:
                row_state[iid] = True
                vals = list(tree.item(iid, "values"))
                vals[0] = "✓"
                tree.item(iid, values=vals)

        def reject_all() -> None:
            for iid in row_state:
                row_state[iid] = False
                vals = list(tree.item(iid, "values"))
                vals[0] = "—"
                tree.item(iid, values=vals)

        btns = ttk.Frame(dialog, padding=12)
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="Все ✓", command=accept_all).pack(side="left")
        ttk.Button(btns, text="Все —", command=reject_all).pack(side="left", padx=6)
        self._accent_button(btns, "Применить выбранные", apply_choices).pack(side="right")
        ttk.Button(btns, text="Закрыть", command=dialog.destroy).pack(side="right", padx=8)
        fit_window_to_screen(dialog, prefer_w=800, prefer_h=440)

    def _on_draft_mark_select(self, _event=None) -> None:
        sel = self.marks_tree.selection()
        has_sel = bool(sel)
        self._set_mark_action_buttons_enabled(has_sel and bool(self._extraction_draft))
        if not self._extraction_draft or not sel:
            self._show_context_placeholder(True)
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._extraction_draft.marks):
            self._show_context_placeholder(False)
            self._set_text(
                self.mark_context_text,
                self._format_mark_context_panel(self._extraction_draft.marks[idx]),
            )
            _log.debug("mark selected idx=%s", idx, extra={"tag": "Заявка"})

    def _show_context_placeholder(self, show: bool) -> None:
        """Показать подсказку или текст контекста марки."""
        if not hasattr(self, "mark_context_text"):
            return
        if show:
            try:
                self.mark_context_text.pack_forget()
            except tk.TclError:
                pass
            if hasattr(self, "_context_placeholder"):
                self._context_placeholder.pack(fill="x", pady=(6, 0))
            self._set_text(self.mark_context_text, "")
        else:
            if hasattr(self, "_context_placeholder"):
                self._context_placeholder.pack_forget()
            self.mark_context_text.pack(fill="both", expand=True, pady=(6, 0))

    def _toggle_draft_mark(self) -> None:
        if not self._extraction_draft:
            return
        sel = self.marks_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        mark = self._extraction_draft.marks[idx]
        mark.accepted = not mark.accepted
        self._revalidate_draft()

    def _format_mark_size(self, mark: MarkValidation) -> str:
        if mark.characteristic_size is None:
            return ""
        unit = "мм²" if mark.size_unit == "mm2" else "мм"
        return f"{mark.characteristic_size:g} {unit}"

    def _apply_parsed_fields_to_mark(self, target: MarkValidation, designation: str) -> None:
        record = parse_cable_mark_record(
            designation,
            document=target.document,
            context=target.context,
        )
        target.mark = record.full_mark
        target.brand = record.brand
        target.fire_class = record.fire_class
        target.cores_count = record.cores_count
        target.structural_element_type = record.structural_element_type
        target.structural_elements_count = record.structural_elements_count
        target.characteristic_size = record.characteristic_size
        target.size_unit = record.size_unit
        if not target.document:
            target.document = record.document

    def _open_mark_editor(
        self,
        existing: MarkValidation | None,
        *,
        title: str,
        save_label: str,
        on_save,
    ) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.minsize(520, 480)
        dialog.configure(bg=COLORS["bg"])
        # Кнопки снизу ВСЕГДА видны (pack bottom first), форма — остаток
        btns = ttk.Frame(dialog, padding=(12, 8, 12, 12))
        btns.pack(side="bottom", fill="x")

        seed = existing or MarkValidation(
            mark="",
            confidence=0.75,
            status=FieldStatus.ok,
            accepted=True,
        )

        fields: dict[str, tk.Variable] = {
            "mark": tk.StringVar(value=seed.mark),
            "brand": tk.StringVar(value=seed.brand or ""),
            "fire_class": tk.StringVar(value=seed.fire_class or ""),
            "cores_count": tk.StringVar(
                value=str(seed.cores_count) if seed.cores_count else ""
            ),
            "structural_element_type": tk.StringVar(
                value=seed.structural_element_type or "жила"
            ),
            "structural_elements_count": tk.StringVar(
                value=str(seed.structural_elements_count)
                if seed.structural_elements_count
                else ""
            ),
            "characteristic_size": tk.StringVar(
                value=str(seed.characteristic_size) if seed.characteristic_size else ""
            ),
            "size_unit": tk.StringVar(value=seed.size_unit or "mm2"),
            "document": tk.StringVar(value=seed.document or ""),
        }

        form = ttk.Frame(dialog, padding=12)
        form.pack(side="top", fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        hint = ttk.Label(
            form,
            text="Измените поля → «Сохранить в заявку». "
            "«Разобрать» заполняет только пустые поля из обозначения.",
            style="Muted.TLabel",
            wraplength=480,
        )
        hint.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        rows = (
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
        for row, (label, key) in enumerate(rows, start=1):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            if key == "structural_element_type":
                ttk.Combobox(
                    form,
                    textvariable=fields[key],
                    values=("жила", "пара", "тройка"),
                    state="readonly",
                    width=24,
                ).grid(row=row, column=1, sticky="ew", pady=4)
            elif key == "size_unit":
                ttk.Combobox(
                    form,
                    textvariable=fields[key],
                    values=("mm2", "mm"),
                    state="readonly",
                    width=24,
                ).grid(row=row, column=1, sticky="w", pady=4)
            else:
                ttk.Entry(form, textvariable=fields[key]).grid(
                    row=row, column=1, sticky="ew", pady=4
                )

        def _parsed_from_designation(designation: str) -> MarkValidation:
            tmp = MarkValidation(
                mark=designation,
                document=fields["document"].get().strip() or None,
                context=seed.context,
                confidence=seed.confidence,
                status=seed.status,
                accepted=seed.accepted,
            )
            try:
                self._apply_parsed_fields_to_mark(tmp, designation)
            except Exception:  # noqa: BLE001
                pass
            return tmp

        def autofill(*, only_empty: bool = True) -> None:
            """only_empty=True — не затирает ручные правки оператора."""
            designation = fields["mark"].get().strip()
            if len(designation) < 3:
                messagebox.showwarning(
                    "Марка", "Сначала укажите условное обозначение.", parent=dialog
                )
                return
            tmp = _parsed_from_designation(designation)
            def set_field(key: str, value: str) -> None:
                if only_empty and fields[key].get().strip():
                    return
                fields[key].set(value)

            fields["mark"].set(tmp.mark or designation)
            set_field("brand", tmp.brand or "")
            set_field("fire_class", tmp.fire_class or "")
            set_field("cores_count", str(tmp.cores_count or ""))
            set_field("structural_element_type", tmp.structural_element_type or "жила")
            set_field(
                "structural_elements_count",
                str(tmp.structural_elements_count or ""),
            )
            set_field(
                "characteristic_size",
                str(tmp.characteristic_size) if tmp.characteristic_size else "",
            )
            if not only_empty or not fields["size_unit"].get().strip():
                fields["size_unit"].set(tmp.size_unit or "mm2")
            if tmp.document:
                set_field("document", tmp.document)

        def autofill_force() -> None:
            if not messagebox.askyesno(
                "Перезаполнить",
                "Заполнить все поля из обозначения заново?\n"
                "Ручные правки в полях ниже будут сброшены.",
                parent=dialog,
            ):
                return
            # временно очищаем производные поля, кроме mark/document
            for key in (
                "brand",
                "fire_class",
                "cores_count",
                "structural_element_type",
                "structural_elements_count",
                "characteristic_size",
            ):
                fields[key].set("")
            fields["structural_element_type"].set("жила")
            autofill(only_empty=False)

        def build_mark() -> MarkValidation | None:
            designation = fields["mark"].get().strip()
            if len(designation) < 3:
                messagebox.showwarning(
                    "Марка", "Укажите условное обозначение кабеля.", parent=dialog
                )
                return None

            # Автоподстановка чисел из обозначения, если поля пустые
            parsed = _parsed_from_designation(designation)
            cores_raw = fields["cores_count"].get().strip()
            elem_raw = fields["structural_elements_count"].get().strip()
            size_raw = fields["characteristic_size"].get().strip().replace(",", ".")
            brand = fields["brand"].get().strip() or parsed.brand
            fire = fields["fire_class"].get().strip() or parsed.fire_class
            elem_type = (
                fields["structural_element_type"].get().strip()
                or parsed.structural_element_type
                or "жила"
            )
            unit = fields["size_unit"].get().strip() or parsed.size_unit or "mm2"

            try:
                cores = int(cores_raw) if cores_raw else int(parsed.cores_count or 1)
                elem_count = (
                    int(elem_raw)
                    if elem_raw
                    else int(parsed.structural_elements_count or cores or 1)
                )
                if size_raw:
                    size = float(size_raw)
                elif parsed.characteristic_size is not None:
                    size = float(parsed.characteristic_size)
                else:
                    size = 1.0
            except ValueError:
                messagebox.showwarning(
                    "Марка",
                    "ТПЖ, кол-во элементов и размер должны быть числами.\n"
                    "Или очистите поля — подставятся из обозначения.",
                    parent=dialog,
                )
                return None
            if cores < 1 or elem_count < 1 or size <= 0:
                messagebox.showwarning(
                    "Марка", "ТПЖ ≥ 1, размер > 0.", parent=dialog
                )
                return None

            # Синхронизируем видимые поля (что реально сохраняем)
            fields["cores_count"].set(str(cores))
            fields["structural_elements_count"].set(str(elem_count))
            fields["characteristic_size"].set(str(size).replace(".", ","))
            if brand and not fields["brand"].get().strip():
                fields["brand"].set(brand)

            return MarkValidation(
                mark=designation,
                document=fields["document"].get().strip() or None,
                context=seed.context,
                requirements_raw=seed.requirements_raw,
                suggested_tests=list(seed.suggested_tests or []),
                brand=brand or None,
                fire_class=fire or None,
                cores_count=cores,
                structural_element_type=elem_type,
                structural_elements_count=elem_count,
                characteristic_size=size,
                size_unit=unit if unit in ("mm2", "mm") else "mm2",
                confidence=seed.confidence,
                status=seed.status,
                warnings=list(seed.warnings),
                accepted=seed.accepted,
            )

        def save() -> None:
            built = build_mark()
            if built is None:
                return
            on_save(built)
            dialog.destroy()
            self._revalidate_draft()
            self.status.set(f"Марка сохранена в заявку: {built.mark[:60]}")

        ttk.Button(
            btns, text="Разобрать (пустые)", command=lambda: autofill(only_empty=True)
        ).pack(side="left")
        ttk.Button(btns, text="Перезаполнить всё…", command=autofill_force).pack(
            side="left", padx=(6, 0)
        )
        # Явная primary-кнопка (tk) — не «теряется» в теме
        self._accent_button(btns, save_label, save).pack(side="right")
        ttk.Button(btns, text="Отмена", command=dialog.destroy).pack(side="right", padx=(0, 8))

        dialog.bind("<Return>", lambda _e: save())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        fit_window_to_screen(dialog, prefer_w=560, prefer_h=520)
        dialog.focus_force()

    def _add_draft_mark(self) -> None:
        if not self._extraction_draft:
            messagebox.showinfo("Заявка", "Сначала извлеките документ.")
            return

        def on_save(built: MarkValidation) -> None:
            self._extraction_draft.marks.append(built)

        self._open_mark_editor(None, title="Добавить марку", save_label="Добавить", on_save=on_save)

    def _remove_draft_mark(self) -> None:
        if not self._extraction_draft:
            return
        sel = self.marks_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        del self._extraction_draft.marks[idx]
        self._revalidate_draft()

    def _edit_draft_mark(self) -> None:
        if not self._extraction_draft:
            messagebox.showinfo("Марка", "Сначала извлеките заявку.")
            return
        sel = self.marks_tree.selection()
        if not sel:
            messagebox.showinfo("Марка", "Выберите марку в таблице, затем «Изменить».")
            return
        idx = int(sel[0])
        mark = self._extraction_draft.marks[idx]

        def on_save(built: MarkValidation) -> None:
            built.accepted = mark.accepted
            built.confidence = max(mark.confidence, 0.85)
            built.status = FieldStatus.ok
            built.warnings = []
            built.context = mark.context
            built.requirements_raw = mark.requirements_raw
            built.suggested_tests = list(mark.suggested_tests or [])
            if self._extraction_draft:
                self._extraction_draft.marks[idx] = built

        self._open_mark_editor(
            mark.model_copy(deep=True),
            title="Изменить марку в заявке",
            save_label="Сохранить в заявку",
            on_save=on_save,
        )

    def _on_draft_mark_double_click(self, event) -> None:
        """Двойной клик — открыть редактор (не сразу в расчёт)."""
        if self.marks_tree.identify_region(event.x, event.y) == "heading":
            return
        # Выделить строку под курсором
        row = self.marks_tree.identify_row(event.y)
        if row:
            self.marks_tree.selection_set(row)
            self.marks_tree.focus(row)
        self._edit_draft_mark()

    def _selected_draft_mark(self) -> MarkValidation | None:
        if not self._extraction_draft or not hasattr(self, "marks_tree"):
            return None
        sel = self.marks_tree.selection()
        if sel:
            idx = int(sel[0])
            if 0 <= idx < len(self._extraction_draft.marks):
                return self._extraction_draft.marks[idx]
        accepted = [m for m in self._extraction_draft.marks if m.accepted]
        if len(accepted) == 1:
            return accepted[0]
        return None

    def _revalidate_draft(self) -> None:
        if not self._extraction_draft:
            return
        accepted_matches = [
            CableMarkMatch(mark=m.mark, context=m.context, document=m.document)
            for m in self._extraction_draft.marks
            if m.accepted
        ]
        interim = self._extraction_draft.result.model_copy(
            update={
                "cable_marks": accepted_matches,
                "customer_name": self.draft_customer_var.get().strip(),
                "manufacturer_name": self.draft_manufacturer_var.get().strip(),
            }
        )
        fresh = validate_extraction(interim)
        fresh_by_mark = {m.mark: m for m in fresh.marks}
        updated_marks: list[MarkValidation] = []
        for entry in self._extraction_draft.marks:
            if entry.accepted and entry.mark in fresh_by_mark:
                fv = fresh_by_mark[entry.mark]
                updated_marks.append(
                    entry.model_copy(
                        update={
                            "confidence": fv.confidence,
                            "status": fv.status,
                            "warnings": fv.warnings,
                        }
                    )
                )
            else:
                updated_marks.append(entry)
        self._extraction_draft.marks = updated_marks
        report = apply_operator_edits(
            fresh,
            marks=updated_marks,
            customer_name=self.draft_customer_var.get().strip(),
            manufacturer_name=self.draft_manufacturer_var.get().strip(),
            text=self._extraction_draft.result.text,
            ocr_used=self._extraction_draft.result.ocr_used,
        )
        self._extraction_draft.report = report.model_copy(update={"marks": updated_marks})
        self._update_validation_warnings(report)
        self._refresh_marks_tree()
        self._update_validation_status_bar(
            state="draft" if not self._extraction_confirmed else "confirmed",
            file_name=Path(self._extraction_draft.source_path).name,
            result=self._extraction_draft.result,
            report=report,
        )

    def _build_confirmed_result(self) -> PdfExtractionResult:
        if not self._extraction_draft:
            raise RuntimeError("Нет черновика заявки")
        from ...generation.lab_profile import is_own_lab_name
        from ...extraction.organization_extractor import normalize_org_name
        from ...models import OrganizationExtract

        accepted = [
            CableMarkMatch(mark=m.mark, context=m.context, document=m.document)
            for m in self._extraction_draft.marks
            if m.accepted
        ]
        customer_name = self.draft_customer_var.get().strip()
        manufacturer_name = self.draft_manufacturer_var.get().strip()
        customer_inn = self.draft_customer_inn_var.get().strip() or None
        customer_addr = self.draft_customer_addr_var.get().strip() or None

        organizations: list = []
        seen_keys: set[str] = set()

        def _append(org: OrganizationExtract) -> None:
            key = normalize_org_name(org.name or "")
            if not key or key in seen_keys:
                return
            if is_own_lab_name(org.name):
                # Наша ИЛ — в result для отображения можно оставить, save отфильтрует
                org = org.model_copy(update={"role": "unknown", "org_type": "testing_center"})
            seen_keys.add(key)
            organizations.append(org)

        for org in self._extraction_draft.result.organizations:
            org_copy = org.model_copy(deep=True)
            if org_copy.role == "customer" and customer_name:
                org_copy.name = customer_name
                if customer_inn:
                    org_copy.inn = customer_inn
                if customer_addr:
                    org_copy.address = customer_addr
            elif org_copy.role == "manufacturer" and manufacturer_name:
                org_copy.name = manufacturer_name
            _append(org_copy)

        # Оператор ввёл заказчика, которого не было в extract — добавить
        if customer_name and normalize_org_name(customer_name) not in seen_keys:
            if not is_own_lab_name(customer_name):
                _append(
                    OrganizationExtract(
                        name=customer_name,
                        inn=customer_inn,
                        address=customer_addr,
                        legal_address=customer_addr,
                        actual_address=customer_addr,
                        org_type="certification_body"
                        if re.search(r"сертификац|фаер|fire", customer_name, re.I)
                        else "unknown",
                        role="customer",
                        confidence=0.95,
                    )
                )
        if manufacturer_name and normalize_org_name(manufacturer_name) not in seen_keys:
            if not is_own_lab_name(manufacturer_name):
                _append(
                    OrganizationExtract(
                        name=manufacturer_name,
                        org_type="manufacturer",
                        role="manufacturer",
                        confidence=0.95,
                    )
                )

        # Гарантировать role=customer на совпадающем имени
        cust_key = normalize_org_name(customer_name) if customer_name else ""
        mfg_key = normalize_org_name(manufacturer_name) if manufacturer_name else ""
        for org in organizations:
            nk = normalize_org_name(org.name)
            if cust_key and nk == cust_key:
                org.role = "customer"
                if customer_inn:
                    org.inn = customer_inn
                if customer_addr:
                    org.address = customer_addr
            if mfg_key and nk == mfg_key:
                org.role = "manufacturer"
                if not org.org_type or org.org_type == "unknown":
                    org.org_type = "manufacturer"

        return self._extraction_draft.result.model_copy(
            update={
                "cable_marks": accepted,
                "customer_name": customer_name,
                "manufacturer_name": manufacturer_name,
                "organizations": organizations,
            }
        )

    def _export_training_corrections(self, result: PdfExtractionResult) -> None:
        if not self._extraction_draft:
            return
        lines: list[str] = []
        # События ассистента пишутся сразу в assistant_*.jsonl — здесь только
        # ручные правки оператора относительно original_marks.
        orig_by_mark = {m.mark: m for m in self._extraction_draft.original_marks}
        for final in self._extraction_draft.marks:
            if not final.accepted:
                continue
            orig = orig_by_mark.get(final.mark)
            if orig is None:
                for o in self._extraction_draft.original_marks:
                    if o.mark in final.mark or final.mark in o.mark:
                        orig = o
                        break
            if orig is None:
                lines.append(
                    json.dumps(
                        {
                            "field": "mark",
                            "change": "added",
                            "corrected": final.model_dump(mode="json"),
                            "doc": Path(result.source_path).name,
                        },
                        ensure_ascii=False,
                    )
                )
                continue
            for field in (
                "mark",
                "brand",
                "document",
                "cores_count",
                "characteristic_size",
                "fire_class",
            ):
                old_val = getattr(orig, field, None)
                new_val = getattr(final, field, None)
                if old_val != new_val:
                    lines.append(
                        json.dumps(
                            {
                                "field": field,
                                "original": old_val,
                                "corrected": new_val,
                                "mark": final.mark,
                                "doc": Path(result.source_path).name,
                            },
                            ensure_ascii=False,
                        )
                    )
        customer = self.draft_customer_var.get().strip()
        if customer and customer != self._extraction_draft.original_customer:
            lines.append(
                json.dumps(
                    {
                        "field": "customer",
                        "original": self._extraction_draft.original_customer,
                        "corrected": customer,
                        "doc": Path(result.source_path).name,
                    },
                    ensure_ascii=False,
                )
            )
        manufacturer = self.draft_manufacturer_var.get().strip()
        original_mfg = getattr(self._extraction_draft, "original_manufacturer", None)
        if original_mfg is None:
            original_mfg = getattr(self._extraction_draft.result, "manufacturer_name", "") or ""
        if manufacturer and manufacturer != (original_mfg or ""):
            lines.append(
                json.dumps(
                    {
                        "field": "manufacturer",
                        "original": original_mfg or "",
                        "corrected": manufacturer,
                        "doc": Path(result.source_path).name,
                    },
                    ensure_ascii=False,
                )
            )
        if not lines:
            return
        out_dir = Path("data/training/corrections")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{Path(result.source_path).stem}.jsonl"
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _prompt_org_dedup(
        self,
        name: str,
        *,
        role_label: str,
    ) -> str:
        """
        Проверка похожих организаций.

        Returns:
            "use:<id>" — взять существующую
            "create" — создать новую
            "skip" — не сохранять
        """
        exact_id = find_organization_id_by_name(name, db_path=self.db_path)
        if exact_id is not None:
            return f"use:{exact_id}"
        similar = find_similar_organizations(
            name, min_ratio=0.82, limit=5, db_path=self.db_path
        )
        # exact уже отфильтрован; похожие < 1.0
        similar = [s for s in similar if s.get("score", 0) < 1.0]
        if not similar:
            return "create"
        lines = "\n".join(
            f"  • {s['name']}  ({s['score']:.0%}"
            + (f", ИНН {s['inn']}" if s.get("inn") else "")
            + ")"
            for s in similar[:5]
        )
        best = similar[0]
        ans = messagebox.askyesnocancel(
            "Похожая организация",
            f"{role_label}: «{name}»\n\n"
            f"В справочнике уже есть похожие записи:\n{lines}\n\n"
            f"Да — использовать «{best['name']}»\n"
            f"Нет — добавить как новую\n"
            f"Отмена — не сохранять эту организацию",
            parent=self,
        )
        if ans is True:
            return f"use:{best['id']}"
        if ans is False:
            return "create"
        return "skip"

    def _save_orgs_with_dedup_prompt(
        self, result: PdfExtractionResult
    ) -> dict[str, int | None]:
        """Confirm: customer/manufacturer → БД с fuzzy-дедупом; ИЛ пропускаем."""
        from ...generation.lab_profile import is_own_lab_name
        from ...extraction.organization_extractor import normalize_org_name
        from ...models import OrganizationExtract

        customer_name = (result.customer_name or "").strip()
        manufacturer_name = (result.manufacturer_name or "").strip()
        customer_inn = self.draft_customer_inn_var.get().strip() or None
        customer_addr = self.draft_customer_addr_var.get().strip() or None

        customer_id: int | None = None
        manufacturer_id: int | None = None

        def _resolve_named(
            name: str,
            *,
            role_label: str,
            org_type: str,
            role: str,
            inn: str | None = None,
            address: str | None = None,
        ) -> int | None:
            if not name or is_own_lab_name(name):
                return None
            decision = self._prompt_org_dedup(name, role_label=role_label)
            if decision == "skip":
                return None
            if decision.startswith("use:"):
                org_id = int(decision.split(":", 1)[1])
                # подтянуть реквизиты, если оператор ввёл ИНН/адрес
                if inn or address:
                    row = get_organization_by_id(org_id, self.db_path)
                    if row:
                        update_organization(
                            org_id,
                            name=row["name"],
                            address=address or row.get("address"),
                            postal_code=row.get("postal_code"),
                            phone=row.get("phone"),
                            email=row.get("email"),
                            inn=inn or row.get("inn"),
                            kpp=row.get("kpp"),
                            is_accredited=bool(row.get("is_accredited")),
                            fsa_registry_number=row.get("fsa_registry_number"),
                            org_type=row.get("org_type") or org_type,
                            db_path=self.db_path,
                        )
                return org_id
            # create
            extract = OrganizationExtract(
                name=name,
                inn=inn,
                address=address,
                legal_address=address,
                actual_address=address,
                org_type=org_type,  # type: ignore[arg-type]
                role=role,  # type: ignore[arg-type]
                confidence=0.95,
            )
            # merge details from extract list if same name
            for o in result.organizations or []:
                if normalize_org_name(o.name) == normalize_org_name(name):
                    extract = o.model_copy(
                        update={
                            "name": name,
                            "inn": inn or o.inn,
                            "address": address or o.address,
                            "role": role,
                            "org_type": o.org_type if o.org_type != "unknown" else org_type,
                        }
                    )
                    break
            from ...persistence.sqlite_repo import upsert_organization

            return upsert_organization(
                extract, source=str(result.source_path), db_path=self.db_path
            )

        if customer_name:
            customer_id = _resolve_named(
                customer_name,
                role_label="Заказчик",
                org_type="certification_body"
                if re.search(r"сертификац|фаер|fire", customer_name, re.I)
                else "unknown",
                role="customer",
                inn=customer_inn,
                address=customer_addr,
            )
        if manufacturer_name:
            manufacturer_id = _resolve_named(
                manufacturer_name,
                role_label="Производитель",
                org_type="manufacturer",
                role="manufacturer",
            )

        # Остальные org из extract (не ИЛ, не уже сохранённые роли) — без лишних вопросов
        for org in result.organizations or []:
            if is_own_lab_name(org.name):
                continue
            if org.org_type == "testing_center":
                continue
            key = normalize_org_name(org.name)
            if customer_name and key == normalize_org_name(customer_name):
                continue
            if manufacturer_name and key == normalize_org_name(manufacturer_name):
                continue
            if org.role in ("customer", "manufacturer") or org.org_type in (
                "manufacturer",
                "certification_body",
                "dealer",
            ):
                try:
                    from ...persistence.sqlite_repo import upsert_organization

                    upsert_organization(
                        org, source=str(result.source_path), db_path=self.db_path
                    )
                except Exception:
                    _log.exception("org upsert skip name=%s", org.name[:60])

        return {
            "customer_org_id": customer_id,
            "manufacturer_org_id": manufacturer_id,
        }

    def _persist_extraction(
        self,
        result: PdfExtractionResult,
        *,
        mark_validations: list[MarkValidation] | None = None,
    ) -> int:
        db_stats = {"saved": 0, "errors": 0}
        if self.save_marks_var.get():
            if mark_validations:
                db_stats = save_cable_marks_from_validations(
                    mark_validations,
                    source=str(result.source_path),
                    db_path=self.db_path,
                )
            elif result.cable_marks:
                db_stats = save_cable_marks_from_matches(
                    result.cable_marks,
                    source=str(result.source_path),
                    db_path=self.db_path,
                )
        org_ids: dict[str, int | None] = {}
        if self.save_orgs_var.get():
            # Всегда пытаемся сохранить заказчика/производителя из полей GUI,
            # даже если extract.organizations пуст (ручной ввод).
            has_org_fields = bool(
                (result.customer_name or "").strip()
                or (result.manufacturer_name or "").strip()
                or result.organizations
            )
            if has_org_fields:
                # fuzzy: если имя новое и есть похожие — спросить оператора
                org_ids = self._save_orgs_with_dedup_prompt(result)
        extraction_id = save_document_extraction(
            source_path=str(result.source_path),
            source_type=result.source_type,
            text=result.text,
            marks_count=len(result.cable_marks),
            customer_org_id=org_ids.get("customer_org_id"),
            manufacturer_org_id=org_ids.get("manufacturer_org_id"),
            db_path=self.db_path,
        )
        self._last_document_extraction_id = extraction_id
        self._last_manufacturer_name = result.manufacturer_name or ""
        return extraction_id

    def _confirm_extraction(self) -> None:
        if not self._extraction_draft:
            messagebox.showinfo("Заявка", "Нет данных для подтверждения.")
            return
        self._revalidate_draft()
        if self._extraction_draft.report.block_confirm:
            _log.warning(
                "confirm blocked flags=%s",
                self._extraction_draft.report.flags[:8],
                extra={"tag": "Заявка"},
            )
            messagebox.showerror(
                "Подтверждение заблокировано",
                "Исправьте критичные поля (красные/⛔) перед сохранением.\n\n"
                + "\n".join(self._extraction_draft.report.flags[:6]),
            )
            return

        accepted_count = sum(1 for m in self._extraction_draft.marks if m.accepted)
        if accepted_count == 0:
            messagebox.showwarning(
                "Заявка",
                "Нет принятых марок. Добавьте или включите хотя бы одну марку.",
            )
            return

        _log.info(
            "confirm extraction marks_accepted=%s total_marks=%s customer=%r manufacturer=%r",
            accepted_count,
            len(self._extraction_draft.marks),
            (self.draft_customer_var.get() or "")[:80],
            (self.draft_manufacturer_var.get() or "")[:80],
            extra={"tag": "Заявка"},
        )
        result = self._build_confirmed_result()
        self.save_marks_var.set(True)
        self.save_orgs_var.set(True)
        self._export_training_corrections(result)
        self._persist_extraction(
            result,
            mark_validations=self._extraction_draft.marks,
        )

        customer_name = result.customer_name
        self._extraction_confirmed = True
        self._extraction_draft.result = result
        self._load_cable_marks()
        if customer_name:
            self.kp_customer_var.set(customer_name)
        self._apply_test_type_from_document(result.text)
        self._load_organizations()

        self._update_validation_status_bar(
            state="confirmed",
            file_name=Path(result.source_path).name,
            result=result,
            report=self._extraction_draft.report,
        )
        self.parse_info_var.set(
            self._format_parse_info(
                file_name=Path(result.source_path).name,
                source_type=result.source_type,
                marks_count=accepted_count,
                customer_name=customer_name,
                manufacturer_name=result.manufacturer_name,
                ocr_used=result.ocr_used,
                page_count=result.page_count,
                extracted_at=result.extracted_at.isoformat(),
                validation_state="confirmed",
            )
        )
        self.status.set("Заявка подтверждена и сохранена")
        messagebox.showinfo(
            "Подтверждено",
            f"Сохранено марок: {accepted_count}\nМожно переходить к расчёту и КП.",
        )

    def _cancel_extraction_draft(self) -> None:
        self._extraction_draft = None
        self._extraction_confirmed = False
        self._refresh_marks_tree()
        self._warn_lines = []
        self._warn_expanded = False
        self.validation_warn_summary_var.set("")
        self.validation_warn_detail.pack_forget()
        self.validation_warn_frame.pack_forget()
        self.draft_customer_var.set("")
        self.draft_customer_inn_var.set("")
        self.draft_customer_addr_var.set("")
        self.draft_manufacturer_var.set("")
        self.draft_recipient_var.set("")
        self._show_context_placeholder(True)
        self._set_text(self.mark_context_text, "")
        # Файл оставляем: можно сразу извлечь повторно
        self._update_validation_status_bar(state="idle")
        self.parse_info_var.set("Заявка не обработана — раздел «Заявки»")
        self.status.set("Черновик отменён")
        _log.info("extraction draft cancelled", extra={"tag": "Заявка"})

    def _browse_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите заявку",
            filetypes=[
                ("Документы заявки", "*.pdf;*.docx;*.xlsx;*.xls;*.png;*.jpg;*.jpeg;*.tif;*.tiff"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Excel", "*.xlsx;*.xls"),
                ("Изображения", "*.png;*.jpg;*.jpeg;*.tif;*.tiff"),
                ("Все файлы", "*.*"),
            ],
        )
        if path:
            self.pdf_path_var.set(path)
            _log.info("browse file=%s", path, extra={"tag": "Заявка"})

    def _on_ocr_engine_toggle(self) -> None:
        """При torch-CV поднимаем DPI по умолчанию (EasyOCR любит крупные глифы)."""
        if self.ocr_pytorch_var.get():
            try:
                cur = int(self.ocr_dpi_var.get())
            except (TypeError, ValueError, tk.TclError):
                cur = SCAN_OCR_DPI
            if cur < EASYOCR_OCR_DPI:
                self.ocr_dpi_var.set(EASYOCR_OCR_DPI)
        else:
            # обратно на скан-default, если пользователь не поднимал вручную выше
            try:
                cur = int(self.ocr_dpi_var.get())
            except (TypeError, ValueError, tk.TclError):
                cur = SCAN_OCR_DPI
            if cur == EASYOCR_OCR_DPI:
                self.ocr_dpi_var.set(SCAN_OCR_DPI)

    def _present_extraction_result(
        self,
        result: PdfExtractionResult,
        *,
        source_path: Path,
        json_stem: str,
        confirm_only: bool,
    ) -> None:
        """Общая сборка черновика после extract (файл или текст)."""
        report = validate_extraction(result)
        _log.info(
            "extract done marks=%s orgs=%s text=%s engine=%s conf=%.2f",
            len(result.cable_marks),
            len(result.organizations),
            len(result.text),
            result.ocr_engine,
            report.overall_confidence,
        )
        out_dir = Path("data/extracted")
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r'[<>:"/\\|?*]', "_", json_stem)[:80] or "extract"
        out_file = out_dir / f"{safe_stem}.json"
        out_file.write_text(
            result.model_dump_json(indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        initial_marks = [m.model_copy(deep=True) for m in report.marks]
        draft = ExtractionDraft(
            result=result,
            report=report,
            source_path=source_path,
            json_path=out_file,
            marks=initial_marks,
            original_marks=[m.model_copy(deep=True) for m in initial_marks],
            original_customer=result.customer_name,
            original_manufacturer=result.manufacturer_name or "",
        )

        def update_ui() -> None:
            self._show_extraction_draft(draft)
            if not confirm_only:
                self.save_marks_var.set(True)
                self.save_orgs_var.set(True)
                confirmed = self._build_confirmed_result()
                self._persist_extraction(
                    confirmed,
                    mark_validations=self._extraction_draft.marks if self._extraction_draft else None,
                )
                self._extraction_confirmed = True
                self._extraction_draft.result = confirmed
                self._load_cable_marks()
                self._load_organizations()
                if confirmed.customer_name:
                    self.kp_customer_var.set(confirmed.customer_name)
                self._update_validation_status_bar(
                    state="confirmed",
                    file_name=source_path.name,
                    result=confirmed,
                    report=draft.report,
                )
                self.status.set(
                    f"Заявка сохранена · марок: {len(confirmed.cable_marks)} · {out_file.name}"
                )
            else:
                n_suggest = 0
                for m in draft.marks:
                    try:
                        from ...assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
                        if suggest_mark_correction(m.mark, db_path=self.db_path).changed:
                            n_suggest += 1
                    except Exception:  # noqa: BLE001
                        pass
                hint = f" · ассистент: {n_suggest} правок" if n_suggest else ""
                self.status.set(
                    f"Черновик · марок: {sum(1 for m in draft.marks if m.accepted)}{hint} · "
                    f"проверьте и подтвердите"
                )

        self.after(0, update_ui)

    def _run_extract_free_text(self) -> None:
        """Вход: текст из речи заказчика / письмо / запрос по ТУ (без файла)."""
        dialog = tk.Toplevel(self)
        dialog.title("Текст заявки (речь / письмо / ТУ)")
        dialog.transient(self)
        dialog.grab_set()
        fit_window_to_screen(dialog, prefer_w=720, prefer_h=480)
        ttk.Label(
            dialog,
            text="Вставьте текст заказчика, письмо или запрос испытаний по ТУ:",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=12, pady=(12, 4))
        text_box = scrolledtext.ScrolledText(dialog, height=18, font=("Segoe UI", 10), wrap="word")
        text_box.pack(fill="both", expand=True, padx=12, pady=4)

        def run_parse() -> None:
            raw = text_box.get("1.0", "end").strip()
            if len(raw) < 10:
                messagebox.showwarning("Текст", "Вставьте осмысленный текст заявки.", parent=dialog)
                return
            dialog.destroy()
            self.status.set("Разбор свободного текста…")
            confirm_only = self.confirm_only_var.get()

            def work() -> None:
                try:
                    from ...extraction.pdf_extractor import extract_from_text
                    result = extract_from_text(raw, source_label="customer_speech")
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    virtual = Path(f"text_customer_{stamp}.txt")
                    self._present_extraction_result(
                        result,
                        source_path=virtual,
                        json_stem=f"text_customer_{stamp}",
                        confirm_only=confirm_only,
                    )
                except Exception as exc:
                    _log.exception("free-text extract failed")

                    def fail() -> None:
                        messagebox.showerror("Текст", str(exc))
                        self.status.set("Ошибка разбора текста")
                        self._update_validation_status_bar(state="error")

                    self.after(0, fail)

            threading.Thread(target=work, daemon=True).start()

        btns = ttk.Frame(dialog, padding=12)
        btns.pack(fill="x")
        ttk.Button(btns, text="Разобрать", style="Accent.TButton", command=run_parse).pack(side="left")
        ttk.Button(btns, text="Отмена", command=dialog.destroy).pack(side="left", padx=8)

    def _open_extract_progress_dialog(self, title: str) -> tuple[tk.Toplevel, tk.StringVar, ttk.Progressbar]:
        """Модальное окно прогресса парсинга (обновляется из worker через after)."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.configure(bg=COLORS["bg"])
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # нельзя закрыть крестиком
        ttk.Label(dlg, text="Извлечение заявки…", font=("Segoe UI Semibold", 11)).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        msg_var = tk.StringVar(value="Подготовка…")
        ttk.Label(dlg, textvariable=msg_var, style="Muted.TLabel", wraplength=420).pack(
            anchor="w", padx=16, pady=(0, 8)
        )
        bar = ttk.Progressbar(dlg, mode="determinate", maximum=100, length=420)
        bar.pack(fill="x", padx=16, pady=(0, 16))
        bar["value"] = 0
        fit_window_to_screen(dlg, prefer_w=460, prefer_h=140)
        dlg.update_idletasks()
        return dlg, msg_var, bar

    def _run_extract_pdf(self) -> None:
        doc_path = self.pdf_path_var.get().strip()
        if not doc_path:
            messagebox.showwarning(
                "Заявка",
                "Выберите файл PDF, Word, Excel или изображение.\n"
                "Или откройте «Параметры OCR» → «Текст…» для ввода речи/письма.",
            )
            return

        eng = "torch-CV" if self.ocr_pytorch_var.get() else "OCR"
        try:
            dpi_show = int(self.ocr_dpi_var.get())
        except (TypeError, ValueError, tk.TclError):
            dpi_show = SCAN_OCR_DPI
        self.status.set(f"Извлечение заявки… ({eng}, DPI {dpi_show})")
        self.render_request_state(RequestPageState.PROCESSING)
        confirm_only = self.confirm_only_var.get()

        prog_dlg, prog_msg, prog_bar = self._open_extract_progress_dialog(
            f"Парсинг · {eng} · DPI {dpi_show}"
        )

        def on_progress(message: str, *, current: int | None = None, total: int | None = None, stage: str = "") -> None:
            def ui() -> None:
                if not prog_dlg.winfo_exists():
                    return
                label = message
                if current is not None and total:
                    label = f"{message}  ({current}/{total})"
                    try:
                        prog_bar["value"] = min(100, max(0, 100.0 * current / total))
                    except tk.TclError:
                        pass
                elif stage == "done":
                    prog_bar["value"] = 100
                prog_msg.set(label)
                self.status.set(label)

            self.after(0, ui)

        def work() -> None:
            try:
                resolved = Path(doc_path).resolve()
                ocr_engine = "easyocr" if self.ocr_pytorch_var.get() else "auto"
                try:
                    dpi = int(self.ocr_dpi_var.get())
                except (TypeError, ValueError, tk.TclError):
                    dpi = SCAN_OCR_DPI
                dpi = max(150, min(dpi, 600))
                _log.info(
                    "extract start file=%s ocr=%s engine=%s dpi=%s",
                    resolved.name,
                    self.ocr_var.get(),
                    ocr_engine,
                    dpi,
                )
                from ...extraction.pdf_extractor import extract_from_document
                result = extract_from_document(
                    Path(doc_path),
                    use_ocr=self.ocr_var.get(),
                    ocr_engine=ocr_engine,
                    ocr_dpi=dpi,
                    progress=on_progress,
                )
                result = result.model_copy(update={"source_path": str(resolved)})

                def finish_ok() -> None:
                    if prog_dlg.winfo_exists():
                        prog_dlg.destroy()
                    self._present_extraction_result(
                        result,
                        source_path=resolved,
                        json_stem=resolved.stem,
                        confirm_only=confirm_only,
                    )

                self.after(0, finish_ok)
            except Exception as exc:
                _log.exception("extract failed")

                def on_error() -> None:
                    if prog_dlg.winfo_exists():
                        prog_dlg.destroy()
                    messagebox.showerror("Ошибка извлечения", str(exc))
                    self.status.set("Ошибка")
                    self._update_validation_status_bar(state="error")

                self.after(0, on_error)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_pdf_opts(self) -> None:
        """Показать/скрыть блок OCR и флагов сохранения (ссылка «Параметры OCR»)."""
        if not hasattr(self, "pdf_opts_frame"):
            return
        if self._pdf_opts_expanded:
            self.pdf_opts_frame.pack_forget()
            self._pdf_opts_expanded = False
            _log.debug("OCR opts collapsed", extra={"tag": "UI"})
            return
        try:
            # Под upload_panel, над mid
            self.pdf_opts_frame.pack(fill="x", pady=(0, 8), before=self._pdf_mid_pane)
        except (tk.TclError, AttributeError):
            self.pdf_opts_frame.pack(fill="x", pady=8)
        self._pdf_opts_expanded = True
        _log.debug("OCR opts expanded", extra={"tag": "UI"})

