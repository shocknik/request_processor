"""
gui.py — графический интерфейс (tkinter).

Запуск: request-processor gui
"""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from ..calculation.climatic_tests import climatic_settings_fields, is_climatic_code
from ..calculation.test_rules import (
    CATEGORY_COLORS,
    CATEGORY_SHORT,
    category_sort_key,
    rule_type_label,
)
from ..logging_setup import get_logger, setup_logging
from ..parsing.cable_mark_parser import parse_cable_mark_record
from ..calculation.cost_calculator import calculate_cost, format_breakdown
from ..validation.extraction_validator import apply_operator_edits, validate_extraction
from ..mapping.requirement_mapper import map_requirements_to_tests
from ..models import (
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
from ..extraction.test_type_extractor import (
    TEST_TYPE_OPTIONS,
    build_kp_subject,
    detect_test_type,
    format_test_type_label,
)
from ..assistant.feedback import AssistantFeedbackEvent, append_assistant_feedback
from ..assistant.models import AssistantContext
from ..extraction.pdf_extractor import (
    DEFAULT_OCR_DPI,
    EASYOCR_OCR_DPI,
    SCAN_OCR_DPI,
)
from .theme import (
    COLORS,
    apply_fluent_theme,
    enable_windows_dpi_awareness,
    fit_window_to_screen,
    make_primary_button,
    make_secondary_button,
)

_log = get_logger("ui.gui")
# generation / extract / ollama / parse_compare — lazy (ускорение холодного старта)
from ..generation.kp_generator import format_money, generate_kp_from_db, proposal_from_calculations
from ..persistence.sqlite_repo import (
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
)

# COLORS импортируются из theme (Fluent Design 2 light)

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
    quantity_var: tk.StringVar | None = None
    row_frame: ttk.Frame | None = field(default=None, repr=False)


@dataclass
class ExtractionDraft:
    """Черновик извлечения до подтверждения оператором."""

    result: PdfExtractionResult
    report: ValidationReport
    source_path: Path
    json_path: Path | None = None
    marks: list[MarkValidation] = field(default_factory=list)
    original_marks: list[MarkValidation] = field(default_factory=list)
    original_customer: str = ""
    # Журнал решений ассистента в рамках этой заявки (→ corrections)
    assistant_events: list[AssistantFeedbackEvent] = field(default_factory=list)
    assistant_session_id: str = ""


class RequestProcessorApp(tk.Tk):
    def __init__(self, db_path: Path = DB_PATH_DEFAULT) -> None:
        super().__init__()
        t0 = time.perf_counter()
        setup_logging(level="INFO")
        self.db_path = Path(db_path)
        self.generated_dir = GENERATED_DIR_DEFAULT
        self.title("Lab_request")
        # 1920×1080 и шире: ~94% экрана (раньше cap 1200×860 — «маленькое» окно)
        fit_window_to_screen(self, prefer_w=1400, prefer_h=900, fill=True)
        self.configure(bg=COLORS["bg"])

        self._tests_by_code: dict[str, dict] = {}
        self._calc_entries: list[CalcTestEntry] = []
        self._calc_picker_vars: dict[str, tk.BooleanVar] = {}
        self._calc_picker_syncing: bool = False
        self.notebook: ttk.Notebook | None = None
        self._last_document_extraction_id: int | None = None
        self._last_manufacturer_name: str = ""
        self._extraction_draft: ExtractionDraft | None = None
        self._extraction_confirmed: bool = False
        self._compare_snapshots_cache: list[dict] = []
        # кэш подсказок ассистента: index → suggested text (для колонки 💡)
        self._assistant_hints: dict[int, str] = {}
        self._pdf_opts_expanded = False

        def _phase(name: str, t_prev: float) -> float:
            now = time.perf_counter()
            _log.info(
                "%s: %.0f ms",
                name,
                (now - t_prev) * 1000,
                extra={"tag": "Старт"},
            )
            return now

        t = _phase("init shell", t0)
        self._ensure_db()
        t = _phase("ensure_db", t)
        self._setup_theme()
        t = _phase("theme", t)
        self._build_ui()
        t = _phase("build_ui", t)
        # Минимальный стартовый набор; сравнение снимков — при первом открытии вкладки
        self._load_history()
        self._load_tests()
        self._load_cable_marks()
        self._load_settings()
        self._load_kp_calculations()
        self._load_organizations()
        self._refresh_parse_info_panel()
        self._load_orders_table()
        self._compare_list_loaded = False
        t = _phase("load_data", t)
        self._install_clipboard_support()
        _log.info(
            "GUI ready total=%.0f ms db=%s screen=%sx%s",
            (time.perf_counter() - t0) * 1000,
            self.db_path,
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            extra={"tag": "Старт"},
        )

    # Классы виджетов с текстом (bind_class — и текущие, и будущие диалоги).
    _CLIPBOARD_CLASSES = (
        "Entry",
        "TEntry",
        "Text",
        "Spinbox",
        "TSpinbox",
        "Combobox",
        "TCombobox",
    )

    def _install_clipboard_support(self) -> None:
        """Стандартные Ctrl+C/X/V/A, Shift+Ins, контекстное меню для всех текстовых полей."""
        for cls in self._CLIPBOARD_CLASSES:
            self.bind_class(cls, "<Control-c>", self._evt_copy)
            self.bind_class(cls, "<Control-C>", self._evt_copy)
            self.bind_class(cls, "<Control-x>", self._evt_cut)
            self.bind_class(cls, "<Control-X>", self._evt_cut)
            self.bind_class(cls, "<Control-v>", self._evt_paste)
            self.bind_class(cls, "<Control-V>", self._evt_paste)
            self.bind_class(cls, "<Control-a>", self._evt_select_all)
            self.bind_class(cls, "<Control-A>", self._evt_select_all)
            # Русская раскладка: keycode (Windows) для C/X/V/A
            self.bind_class(cls, "<Control-KeyPress>", self._evt_ctrl_keycode)
            self.bind_class(cls, "<Shift-Insert>", self._evt_paste)
            self.bind_class(cls, "<Control-Insert>", self._evt_copy)
            self.bind_class(cls, "<Shift-Delete>", self._evt_cut)
            self.bind_class(cls, "<Button-3>", self._evt_context_menu)
        # Label: ПКМ → копировать весь текст (получатель и др.)
        self.bind_class("TLabel", "<Button-3>", self._evt_label_copy_menu)
        self.bind_class("Label", "<Button-3>", self._evt_label_copy_menu)

    def _evt_ctrl_keycode(self, event: tk.Event) -> str | None:
        """Ctrl+C/X/V/A при русской раскладке (символ не 'c', но keycode тот же)."""
        # Windows virtual key codes
        code = int(getattr(event, "keycode", 0) or 0)
        if code == 67:  # C
            return self._evt_copy(event)
        if code == 88:  # X
            return self._evt_cut(event)
        if code == 86:  # V
            return self._evt_paste(event)
        if code == 65:  # A
            return self._evt_select_all(event)
        return None

    def _evt_copy(self, event: tk.Event) -> str:
        self._copy_widget_selection(event.widget)
        return "break"

    def _evt_cut(self, event: tk.Event) -> str:
        self._cut_widget_selection(event.widget)
        return "break"

    def _evt_paste(self, event: tk.Event) -> str:
        self._paste_into_widget(event.widget)
        return "break"

    def _evt_select_all(self, event: tk.Event) -> str:
        self._select_all_widget(event.widget)
        return "break"

    def _evt_context_menu(self, event: tk.Event) -> str:
        self._show_text_context_menu(event, event.widget)
        return "break"

    def _evt_label_copy_menu(self, event: tk.Event) -> str | None:
        widget = event.widget
        try:
            text = str(widget.cget("text") or "")
        except tk.TclError:
            text = ""
        if not text.strip():
            return None
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(
            label="Копировать",
            command=lambda t=text: self._clipboard_set(t),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _clipboard_set(self, text: str) -> None:
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
        except tk.TclError:
            pass

    def _clipboard_get(self) -> str:
        try:
            return str(self.clipboard_get())
        except tk.TclError:
            return ""

    def _widget_is_editable(self, widget: tk.Misc) -> bool:
        try:
            state = str(widget.cget("state"))
        except tk.TclError:
            return True
        return state not in ("disabled", "readonly")

    def _copy_widget_selection(self, widget: tk.Misc) -> None:
        text = self._get_widget_selection(widget)
        if not text:
            # Нет выделения — копируем всё содержимое поля (удобно для «Производитель»).
            text = self._get_widget_all_text(widget)
        self._clipboard_set(text)

    def _cut_widget_selection(self, widget: tk.Misc) -> None:
        if not self._widget_is_editable(widget):
            self._copy_widget_selection(widget)
            return
        text = self._get_widget_selection(widget)
        if not text:
            return
        self._clipboard_set(text)
        cls = widget.winfo_class()
        try:
            if cls in ("Entry", "TEntry", "Combobox", "TCombobox", "Spinbox", "TSpinbox"):
                try:
                    widget.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
            elif cls in ("Text",):
                if widget.tag_ranges("sel"):
                    widget.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

    def _paste_into_widget(self, widget: tk.Misc) -> None:
        if not self._widget_is_editable(widget):
            return
        clip = self._clipboard_get()
        if not clip:
            return
        cls = widget.winfo_class()
        try:
            if cls in ("Entry", "TEntry", "Combobox", "TCombobox", "Spinbox", "TSpinbox"):
                try:
                    widget.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
                widget.insert("insert", clip)
            elif cls in ("Text",):
                try:
                    if widget.tag_ranges("sel"):
                        widget.delete("sel.first", "sel.last")
                except tk.TclError:
                    pass
                widget.insert("insert", clip)
        except tk.TclError:
            pass

    def _get_widget_all_text(self, widget: tk.Misc) -> str:
        cls = widget.winfo_class()
        try:
            if cls in ("Entry", "TEntry", "Combobox", "TCombobox", "Spinbox", "TSpinbox"):
                return str(widget.get())
            if cls in ("Text",):
                return widget.get("1.0", "end-1c")
        except tk.TclError:
            return ""
        return ""

    def _get_widget_selection(self, widget: tk.Misc) -> str:
        cls = widget.winfo_class()
        try:
            if cls in ("Entry", "TEntry", "Combobox", "TCombobox", "Spinbox", "TSpinbox"):
                try:
                    start = widget.index("sel.first")
                    end = widget.index("sel.last")
                    return str(widget.get())[int(start) : int(end)]
                except (tk.TclError, ValueError, TypeError):
                    return ""
            if cls in ("Text",):
                was_disabled = str(widget.cget("state")) == "disabled"
                if was_disabled:
                    widget.configure(state="normal")
                try:
                    if widget.tag_ranges("sel"):
                        return widget.get("sel.first", "sel.last")
                finally:
                    if was_disabled:
                        widget.configure(state="disabled")
        except tk.TclError:
            return ""
        return ""

    def _select_all_widget(self, widget: tk.Misc) -> None:
        cls = widget.winfo_class()
        try:
            if cls in ("Entry", "TEntry", "Combobox", "TCombobox", "Spinbox", "TSpinbox"):
                widget.selection_range(0, "end")
                try:
                    widget.icursor("end")
                except tk.TclError:
                    pass
                try:
                    widget.focus_set()
                except tk.TclError:
                    pass
                return
            if cls in ("Text",):
                was_disabled = str(widget.cget("state")) == "disabled"
                if was_disabled:
                    widget.configure(state="normal")
                try:
                    widget.tag_add("sel", "1.0", "end-1c")
                    widget.mark_set("insert", "1.0")
                    widget.see("1.0")
                    widget.focus_set()
                finally:
                    if was_disabled:
                        # оставляем normal для readonly-текста (см. _make_readonly_text)
                        if getattr(widget, "_rp_readonly", False):
                            pass
                        else:
                            widget.configure(state="disabled")
        except tk.TclError:
            pass

    def _show_text_context_menu(self, event: tk.Event, widget: tk.Misc) -> None:
        editable = self._widget_is_editable(widget)
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Вырезать", command=lambda: self._cut_widget_selection(widget))
        menu.add_command(label="Копировать", command=lambda: self._copy_widget_selection(widget))
        menu.add_command(label="Вставить", command=lambda: self._paste_into_widget(widget))
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=lambda: self._select_all_widget(widget))
        if not editable:
            menu.entryconfigure("Вырезать", state="disabled")
            menu.entryconfigure("Вставить", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _make_readonly_text(self, parent: tk.Misc, **kwargs) -> scrolledtext.ScrolledText:
        """Текстовое поле только для чтения, но с выделением и копированием."""
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("font", ("Segoe UI", 10))
        kwargs.pop("state", None)
        widget = scrolledtext.ScrolledText(parent, **kwargs)
        widget._rp_readonly = True  # type: ignore[attr-defined]

        def _block_edit(event: tk.Event) -> str | None:
            # Разрешаем навигацию и Ctrl-комбинации; ввод — нет.
            if event.state & 0x4:  # Control
                return None
            if event.keysym in (
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Next",
                "Prior",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
                "Alt_L",
                "Alt_R",
                "Escape",
                "Tab",
                "ISO_Left_Tab",
            ):
                return None
            return "break"

        widget.bind("<Key>", _block_edit, add="+")
        return widget

    def _accent_button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        """Primary — синий фон, белый текст (всегда читается)."""
        btn = make_primary_button(parent, text, command)
        # disabled: светло-синий + белый (не серый-на-сером)
        btn.configure(
            disabledforeground=COLORS.get("text_on_accent", "#ffffff"),
        )
        return btn

    def _secondary_button(self, parent: tk.Misc, text: str, command) -> tk.Button:
        """Secondary — белый + тёмный текст + обводка."""
        return make_secondary_button(parent, text, command)

    def _set_button_enabled(self, btn: tk.Button | None, enabled: bool) -> None:
        """Вкл/выкл с сохранением Fluent-цветов (tk иначе серит фон)."""
        if btn is None:
            return
        if enabled:
            btn.configure(
                state="normal",
                bg=COLORS["accent"],
                fg=COLORS.get("text_on_accent", "#ffffff"),
                cursor="hand2",
            )
        else:
            btn.configure(
                state="disabled",
                bg=COLORS.get("accent_disabled", "#a9d0ef"),
                fg=COLORS.get("text_on_accent", "#ffffff"),
                disabledforeground=COLORS.get("text_on_accent", "#ffffff"),
                cursor="arrow",
            )

    def _ensure_db(self) -> None:
        if not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            init_db(self.db_path)
        else:
            from ..persistence.sqlite_repo import _seed_default_settings, migrate_db

            migrate_db(self.db_path)
            _seed_default_settings(self.db_path)

    def _setup_theme(self) -> None:
        apply_fluent_theme(self)

    def _on_root_configure(self, event: tk.Event) -> None:
        """Подстроить wraplength инфо-полосы под ширину окна (FHD и шире)."""
        if event.widget is not self:
            return
        label = getattr(self, "parse_info_label", None)
        if label is None:
            return
        # поля: padding parse_bar + accent strip
        wrap = max(480, int(event.width) - 80)
        try:
            if int(label.cget("wraplength") or 0) != wrap:
                label.configure(wraplength=wrap)
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        # Fluent 2: brand strip + white title bar
        tk.Frame(self, bg=COLORS.get("header_bar", COLORS["accent"]), height=3).pack(fill="x")

        header_wrap = tk.Frame(self, bg=COLORS["header_bg"])
        header_wrap.pack(fill="x")
        header = tk.Frame(header_wrap, bg=COLORS["header_bg"], padx=20, pady=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Lab_request",
            bg=COLORS["header_bg"],
            fg=COLORS["header_text"],
            font=("Segoe UI Semibold", 18, "bold"),
        ).pack(side="left")
        chip = tk.Frame(header, bg=COLORS["accent_light"], padx=10, pady=4)
        chip.pack(side="left", padx=(16, 0))
        tk.Label(
            chip,
            text="1 → 2 → 3 → 4",
            bg=COLORS["accent_light"],
            fg=COLORS["accent"],
            font=("Segoe UI Semibold", 9),
        ).pack()
        tk.Label(
            header,
            text="заявка  →  расчёт  →  КП  →  заказ",
            bg=COLORS["header_bg"],
            fg=COLORS["header_muted"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(12, 0))
        tk.Frame(header_wrap, bg=COLORS["border"], height=1).pack(fill="x")

        parse_bar = tk.Frame(self, bg=COLORS["parse_bg"], padx=20, pady=10)
        parse_bar.pack(fill="x")
        tk.Frame(parse_bar, bg=COLORS["accent"], width=3).pack(side="left", fill="y", padx=(0, 12))
        parse_inner = tk.Frame(parse_bar, bg=COLORS["parse_bg"])
        parse_inner.pack(side="left", fill="x", expand=True)
        self.parse_info_var = tk.StringVar(value="Документ не обработан — начните с вкладки «1. Заявка»")
        self.parse_info_label = tk.Label(
            parse_inner,
            textvariable=self.parse_info_var,
            bg=COLORS["parse_bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 10),
            wraplength=1600,
            justify="left",
            anchor="w",
        )
        self.parse_info_label.pack(fill="x")
        self.bind("<Configure>", self._on_root_configure, add="+")

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
        self.tab_compare = ttk.Frame(self.notebook, padding=10)
        self.tab_marks = ttk.Frame(self.notebook, padding=10)
        self.tab_orgs = ttk.Frame(self.notebook, padding=10)
        self.tab_tests = ttk.Frame(self.notebook, padding=10)
        self.tab_history = ttk.Frame(self.notebook, padding=10)
        self.tab_settings = ttk.Frame(self.notebook, padding=10)
        self.tab_journal = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.tab_pdf, text="  1. Заявка  ")
        self.notebook.add(self.tab_calc, text="  2. Расчёт  ")
        self.notebook.add(self.tab_kp, text="  3. КП  ")
        self.notebook.add(self.tab_orders, text="  4. Заказы  ")
        self.notebook.add(self.tab_compare, text="  5. Сравнение  ")
        self.notebook.add(self.tab_marks, text="  6. Марки  ")
        self.notebook.add(self.tab_orgs, text="  7. Организации  ")
        self.notebook.add(self.tab_tests, text="  8. Справочник  ")
        self.notebook.add(self.tab_history, text="  9. История  ")
        self.notebook.add(self.tab_settings, text="  10. Настройки  ")
        self.notebook.add(self.tab_journal, text="  11. Журнал  ")

        self._build_pdf_tab()
        self._build_calc_tab()
        self._build_kp_tab()
        self._build_orders_tab()
        self._build_compare_tab()
        self._build_marks_tab()
        self._build_orgs_tab()
        self._build_tests_tab()
        self._build_history_tab()
        self._build_settings_tab()
        self._build_journal_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

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

    def _build_pdf_tab(self) -> None:
        bottom = ttk.Frame(self.tab_pdf)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))

        status_row = tk.Frame(bottom, bg=COLORS["parse_bg"], padx=12, pady=8)
        status_row.pack(fill="x")
        self.validation_status_bar = tk.Frame(status_row, bg=COLORS["parse_bg"], width=4)
        self.validation_status_bar.pack(side="left", fill="y", padx=(0, 10))
        self.validation_status_var = tk.StringVar(value="Документ не обработан")
        tk.Label(
            status_row,
            textvariable=self.validation_status_var,
            bg=COLORS["parse_bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        btn_row = ttk.Frame(bottom)
        btn_row.pack(fill="x", pady=(6, 0))
        self._secondary_button(btn_row, "Перепарсить", self._run_extract_pdf).pack(side="left")
        self._secondary_button(btn_row, "Отменить", self._cancel_extraction_draft).pack(side="left", padx=8)
        self._secondary_button(btn_row, "Сохранить снимок", self._save_parse_snapshot).pack(
            side="left", padx=(8, 0)
        )
        self.confirm_btn = self._accent_button(
            btn_row, "Подтвердить заявку", self._confirm_extraction
        )
        self.confirm_btn.pack(side="right")

        top = ttk.Frame(self.tab_pdf)
        top.pack(fill="x")

        self.pdf_path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.pdf_path_var).pack(side="left", fill="x", expand=True, ipady=3)
        ttk.Button(top, text="Обзор…", command=self._browse_pdf).pack(side="left", padx=6)
        self._accent_button(top, "Извлечь", self._run_extract_pdf).pack(side="left", padx=(0, 4))
        self.confirm_btn_top = self._accent_button(
            top, "Подтвердить заявку", self._confirm_extraction
        )
        self.confirm_btn_top.pack(side="left", padx=(4, 0))
        more = ttk.Menubutton(top, text="Ещё ▾")
        more_menu = tk.Menu(more, tearoff=0)
        more_menu.add_command(label="Текст…", command=self._run_extract_free_text)
        more_menu.add_command(label="Снимок парсинга", command=self._save_parse_snapshot)
        more_menu.add_separator()
        more_menu.add_command(label="Параметры OCR / сохранения…", command=self._toggle_pdf_opts)
        more["menu"] = more_menu
        more.pack(side="left", padx=(8, 0))

        # OCR и флаги сохранения — свёрнуты по умолчанию (меньше визуального шума)
        self.pdf_opts_frame = ttk.Frame(self.tab_pdf)
        opts = self.pdf_opts_frame
        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="OCR для сканов", variable=self.ocr_var).pack(side="left")
        self.ocr_pytorch_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts,
            text="torch-CV (эксперимент)",
            variable=self.ocr_pytorch_var,
            command=self._on_ocr_engine_toggle,
        ).pack(side="left", padx=(10, 0))
        ttk.Label(opts, text="DPI:", style="Muted.TLabel").pack(side="left", padx=(12, 2))
        self.ocr_dpi_var = tk.IntVar(value=SCAN_OCR_DPI)  # default 400
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
        ).pack(side="left", padx=(8, 0))
        self.save_marks_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Марки в БД сразу", variable=self.save_marks_var).pack(
            side="left", padx=(12, 0)
        )
        self.save_orgs_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Орг. в БД сразу", variable=self.save_orgs_var).pack(
            side="left", padx=(8, 0)
        )

        # Предупреждения: компактная полоса (не выталкивает марки/организации вниз).
        # Полный список — в ScrolledText по кнопке «Подробнее».
        self._warn_expanded = False
        self._warn_lines: list[str] = []
        self.validation_warn_frame = tk.Frame(self.tab_pdf, bg=COLORS["warn_bg"], padx=8, pady=4)
        warn_header = tk.Frame(self.validation_warn_frame, bg=COLORS["warn_bg"])
        warn_header.pack(fill="x")
        self.validation_warn_summary_var = tk.StringVar(value="")
        tk.Label(
            warn_header,
            textvariable=self.validation_warn_summary_var,
            bg=COLORS["warn_bg"],
            fg="#92400e",
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self._warn_toggle_btn = tk.Button(
            warn_header,
            text="Подробнее",
            command=self._toggle_validation_warnings,
            bg=COLORS["warn_bg"],
            fg="#92400e",
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
            fg="#92400e",
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        # detail показывается только при expand
        self.validation_warn_var = self.validation_warn_summary_var  # back-compat alias

        # mid pack first among expandables so оно всегда забирает остаток высоты
        mid = ttk.PanedWindow(self.tab_pdf, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=(4, 4))
        self._pdf_mid_pane = mid

        left = ttk.LabelFrame(mid, text="Марки — проверьте и отметьте", padding=8, style="Card.TLabelframe")
        mid.add(left, weight=3)
        # Две короткие строки кнопок — не вылезают за край на узком экране
        mark_tb1 = ttk.Frame(left, style="Card.TFrame")
        mark_tb1.pack(fill="x", pady=(0, 2))
        ttk.Button(mark_tb1, text="+", width=3, command=self._add_draft_mark).pack(side="left")
        ttk.Button(mark_tb1, text="Изменить", command=self._edit_draft_mark).pack(side="left", padx=(4, 0))
        ttk.Button(mark_tb1, text="Удалить", command=self._remove_draft_mark).pack(side="left", padx=(4, 0))
        ttk.Button(mark_tb1, text="✓/—", width=4, command=self._toggle_draft_mark).pack(
            side="left", padx=(4, 0)
        )
        self._accent_button(mark_tb1, "→ В расчёт", self._use_mark_in_calc).pack(
            side="left", padx=(10, 0)
        )
        mark_tb2 = ttk.Frame(left, style="Card.TFrame")
        mark_tb2.pack(fill="x", pady=(0, 6))
        self._secondary_button(
            mark_tb2, "Ассистент 💡", self._open_assistant_review_dialog
        ).pack(side="left")
        ttk.Button(
            mark_tb2, text="Принять", command=self._accept_assistant_for_selected
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            mark_tb2, text="Отклонить", command=self._reject_assistant_for_selected
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            mark_tb2,
            text="двойной клик — изменить · 💡 в таблице — есть подсказка",
            style="CardMuted.TLabel",
        ).pack(side="left", padx=(10, 0))

        cols = (
            "accepted",
            "hint",
            "mark",
            "brand",
            "cores",
            "size",
            "document",
            "status",
            "confidence",
        )
        self.marks_tree = ttk.Treeview(left, columns=cols, show="headings", height=12)
        for col, title, width, stretch in (
            ("accepted", "✓", 28, False),
            ("hint", "💡", 28, False),
            ("mark", "Усл. обозначение", 260, True),
            ("brand", "Марка", 80, False),
            ("cores", "ТПЖ", 40, False),
            ("size", "Размер", 60, False),
            ("document", "ТУ/ГОСТ", 140, True),
            ("status", "!", 28, False),
            ("confidence", "%", 40, False),
        ):
            self.marks_tree.heading(col, text=title)
            anchor = "center" if col in ("accepted", "hint", "status", "confidence") else "w"
            self.marks_tree.column(col, width=width, anchor=anchor, stretch=stretch, minwidth=width)
        self.marks_tree.tag_configure("ok", background=COLORS["card"])
        self.marks_tree.tag_configure("warning", background=COLORS["warn_bg"])
        self.marks_tree.tag_configure("error", background=COLORS["error_bg"])
        self.marks_tree.tag_configure("rejected", background="#f1f5f9", foreground=COLORS["muted"])
        self.marks_tree.tag_configure("assist", background="#e8f4fc")
        self.marks_tree.pack(fill="both", expand=True)
        self.marks_tree.bind("<<TreeviewSelect>>", self._on_draft_mark_select)
        self.marks_tree.bind("<Double-Button-1>", self._on_draft_mark_double_click)
        self.marks_tree.bind("<Return>", lambda _e: self._use_mark_in_calc())

        right = ttk.LabelFrame(mid, text="Организации", padding=8, style="Card.TLabelframe")
        mid.add(right, weight=2)
        org_form = ttk.Frame(right, style="Card.TFrame")
        org_form.pack(fill="x")
        org_form.columnconfigure(1, weight=1)

        self.draft_customer_var = tk.StringVar()
        self.draft_customer_inn_var = tk.StringVar()
        self.draft_customer_addr_var = tk.StringVar()
        self.draft_manufacturer_var = tk.StringVar()
        self.draft_recipient_var = tk.StringVar()

        labels = (
            ("Заказчик:", self.draft_customer_var),
            ("ИНН:", self.draft_customer_inn_var),
            ("Адрес:", self.draft_customer_addr_var),
            ("Производитель:", self.draft_manufacturer_var),
            ("Получатель (ИЛ):", self.draft_recipient_var),
        )
        for row, (label, var) in enumerate(labels):
            ttk.Label(org_form, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky="w", pady=4, padx=(0, 8)
            )
            # Обычный Entry: Ctrl+C/V/X/A и ПКМ; получатель — тоже (раньше был Label без копирования).
            ttk.Entry(org_form, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)

        ttk.Label(right, text="Контекст выбранной марки:", style="CardMuted.TLabel").pack(
            anchor="w", pady=(12, 4)
        )
        self.mark_context_text = self._make_readonly_text(
            right,
            height=4,
            font=("Segoe UI", 9),
            bg="#f8fafc",
            relief="flat",
        )
        self.mark_context_text.pack(fill="both", expand=True)

        self._on_confirm_only_toggle()
        self._update_validation_status_bar(state="idle")

    def _build_marks_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_marks)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_cable_marks).pack(side="left")
        self.marks_search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.marks_search_var, width=32).pack(side="left", padx=8, ipady=2)
        ttk.Button(toolbar, text="Поиск", command=self._load_cable_marks).pack(side="left")
        ttk.Button(toolbar, text="Удалить…", command=self._delete_selected_cable_mark).pack(
            side="left", padx=(12, 0)
        )

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

        ttk.Label(grid, text="Вид испытаний:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=4
        )
        self.kp_test_type_var = tk.StringVar(value="Периодические")
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
        from ..generation.lab_profile import KP_STYLES, load_lab_profile

        self.kp_style_var = tk.StringVar(value=load_lab_profile().kp_style)
        ttk.Combobox(
            action,
            textvariable=self.kp_style_var,
            values=list(KP_STYLES),
            width=10,
            state="readonly",
        ).pack(side="left", padx=(0, 10))
        self._accent_button(action, "Сформировать КП", self._run_generate_kp).pack(side="left")
        self._secondary_button(
            action, "3 образца бланка", self._generate_kp_style_previews
        ).pack(side="left", padx=(8, 0))
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
        self._accent_button(toolbar, "Пакет документов", self._build_order_document_pack).pack(
            side="left", padx=(8, 0)
        )
        self._secondary_button(
            toolbar, "JSON → protocol_generator", self._export_order_protocol_meta
        ).pack(side="left", padx=(8, 0))
        self._secondary_button(toolbar, "Обновить", self._load_orders_table).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="Удалить заказ…", command=self._delete_selected_order).pack(
            side="left", padx=(8, 0)
        )
        orders_more = ttk.Menubutton(toolbar, text="Ещё ▾")
        om = tk.Menu(orders_more, tearoff=0)
        om.add_command(label="Макет протокола (простой)", command=self._generate_order_protocol)
        om.add_command(label="Открыть КП", command=self._open_selected_order_kp)
        om.add_command(label="Открыть заявку", command=self._open_selected_order_application)
        om.add_separator()
        om.add_command(label="Печать КП", command=self._print_selected_order_kp)
        om.add_command(label="Печать заявки", command=self._print_selected_order_application)
        orders_more["menu"] = om
        orders_more.pack(side="left", padx=(8, 0))
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
        self.orders_tree.bind(
            "<Button-3>",
            lambda e: self._show_orders_context_menu(e),
        )

        right = ttk.LabelFrame(paned, text="Информация о заказе", padding=8, style="Card.TLabelframe")
        paned.add(right, weight=1)
        self.order_details = self._make_readonly_text(
            right,
            height=20,
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
        ttk.Button(toolbar, text="Удалить…", command=self._delete_selected_organization).pack(
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

    def _build_journal_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_journal)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Обновить", command=self._load_journal_tail).pack(side="left")
        ttk.Label(
            toolbar,
            text="Хвост data/logs/app_YYYY-MM-DD.log (удобно читать оператору)",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)
        self.journal_text = self._make_readonly_text(
            self.tab_journal,
            height=28,
            font=("Consolas", 9),
            bg="#0f172a",
            fg="#e2e8f0",
            wrap="none",
        )
        # dark console-like
        try:
            self.journal_text.configure(bg="#0f172a", fg="#e2e8f0", insertbackground="#e2e8f0")
        except tk.TclError:
            pass
        self.journal_text.pack(fill="both", expand=True)

    def _load_journal_tail(self, lines: int = 250) -> None:
        if not hasattr(self, "journal_text"):
            return
        from ..config import LOGS_DIR
        from datetime import date

        log_path = LOGS_DIR / f"app_{date.today().isoformat()}.log"
        if not log_path.is_file():
            self._set_text(self.journal_text, f"Файл лога пока пуст:\n{log_path}")
            return
        try:
            raw = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = raw[-lines:] if len(raw) > lines else raw
            self._set_text(
                self.journal_text,
                f"# {log_path}  (последние {len(tail)} строк)\n\n" + "\n".join(tail),
            )
        except OSError as exc:
            self._set_text(self.journal_text, f"Не удалось прочитать лог:\n{exc}")

    def _generate_kp_style_previews(self) -> None:
        try:
            from ..generation.kp_generator import render_kp_style_previews

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

    def _build_history_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_history)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_history).pack(side="left")
        ttk.Button(toolbar, text="Удалить расчёт…", command=self._delete_selected_calculation).pack(
            side="left", padx=(12, 0)
        )

        cols = ("id", "created_at", "mark", "total", "source")
        self.history_tree = ttk.Treeview(self.tab_history, columns=cols, show="headings", height=24)
        for col, title, width in (
            ("id", "ID", 50),
            ("created_at", "Дата", 140),
            ("mark", "Марка", 520),
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

    def _build_compare_tab(self) -> None:
        """Снимки парсинга: список, сохранение, сравнение A/B."""
        hint = ttk.Label(
            self.tab_compare,
            text="Сохраняйте прогоны (разный OCR/DPI) и сравнивайте марки, организации и quality-score.",
            style="Muted.TLabel",
            wraplength=900,
        )
        hint.pack(anchor="w", pady=(0, 8))

        paned = ttk.PanedWindow(self.tab_compare, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(paned, text="Снимки", padding=8, style="Card.TLabelframe")
        paned.add(left, weight=2)
        toolbar = ttk.Frame(left, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 6))
        self._secondary_button(toolbar, "Обновить", self._refresh_compare_list).pack(side="left")
        self._secondary_button(toolbar, "Сохранить текущий", self._save_parse_snapshot).pack(
            side="left", padx=6
        )
        self._accent_button(toolbar, "Сравнить A/B", self._run_compare_selected).pack(side="left", padx=6)

        cols = ("id", "created", "label", "engine", "dpi", "marks", "quality")
        self.compare_tree = ttk.Treeview(
            left, columns=cols, show="headings", height=14, selectmode="extended"
        )
        headings = {
            "id": ("ID", 140),
            "created": ("Создан", 130),
            "label": ("Подпись", 200),
            "engine": ("OCR", 80),
            "dpi": ("DPI", 50),
            "marks": ("Марки", 55),
            "quality": ("Quality", 60),
        }
        for key, (title, width) in headings.items():
            self.compare_tree.heading(key, text=title)
            self.compare_tree.column(key, width=width, stretch=key in ("label", "id"))
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.compare_tree.yview)
        self.compare_tree.configure(yscrollcommand=scroll.set)
        self.compare_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        right = ttk.LabelFrame(paned, text="Сравнение / метрики", padding=8, style="Card.TLabelframe")
        paned.add(right, weight=2)
        ttk.Label(
            right,
            text="Выберите 2 снимка (Ctrl+клик) → «Сравнить A/B».",
            style="CardMuted.TLabel",
        ).pack(anchor="w")
        self.compare_report = self._make_readonly_text(
            right, height=22, wrap="word", font=("Consolas", 9), bg=COLORS["card"]
        )
        self.compare_report.pack(fill="both", expand=True, pady=(6, 0))

    def _refresh_compare_list(self) -> None:
        if not hasattr(self, "compare_tree"):
            return
        from ..parse_compare import list_snapshots

        self._compare_snapshots_cache = list_snapshots(limit=100)
        for item in self.compare_tree.get_children():
            self.compare_tree.delete(item)
        for row in self._compare_snapshots_cache:
            self.compare_tree.insert(
                "",
                "end",
                iid=row["id"],
                values=(
                    row["id"],
                    (row.get("created_at") or "")[:19].replace("T", " "),
                    (row.get("label") or "")[:60],
                    row.get("ocr_engine") or "—",
                    row.get("ocr_dpi") or "—",
                    row.get("marks_count", 0),
                    f"{float(row.get('quality_score') or 0):.2f}",
                ),
            )

    def _save_parse_snapshot(self) -> None:
        draft = self._extraction_draft
        if draft is None or draft.result is None:
            messagebox.showinfo("Снимок", "Сначала извлеките документ (вкладка «1. Заявка»).")
            return
        label = simpledialog.askstring(
            "Снимок парсинга",
            "Подпись снимка (например: tesseract DPI300 / easyocr DPI400):",
            initialvalue=(
                f"{Path(draft.result.source_path).stem} · "
                f"{draft.result.ocr_engine or 'no-ocr'}"
            ),
            parent=self,
        )
        if label is None:
            return
        try:
            dpi = int(self.ocr_dpi_var.get())
        except Exception:
            dpi = None
        try:
            from ..parse_compare import save_snapshot_from_extraction

            snap = save_snapshot_from_extraction(
                draft.result,
                label=label.strip() or "",
                notes="",
                ocr_dpi=dpi,
            )
            _log.info(
                "parse snapshot saved id=%s marks=%s quality=%s engine=%s",
                snap.id,
                snap.metrics.marks_count,
                snap.metrics.quality_score,
                snap.ocr_engine,
            )
            self.status.set(f"Снимок сохранён: {snap.id}")
            self._refresh_compare_list()
            messagebox.showinfo(
                "Снимок",
                f"Сохранено: {snap.id}\n"
                f"Марок: {snap.metrics.marks_count}  quality: {snap.metrics.quality_score}\n"
                f"OCR: {snap.ocr_engine or '—'}  DPI: {dpi or '—'}",
            )
        except Exception as exc:
            _log.exception("save snapshot failed")
            messagebox.showerror("Снимок", str(exc))

    def _run_compare_selected(self) -> None:
        sel = list(self.compare_tree.selection())
        if len(sel) != 2:
            messagebox.showinfo("Сравнение", "Выберите ровно 2 снимка (Ctrl+клик).")
            return
        try:
            from ..parse_compare import compare_snapshots, load_snapshot

            a = load_snapshot(sel[0])
            b = load_snapshot(sel[1])
            report = compare_snapshots(a, b)
            lines = [
                f"A: {a.id}",
                f"   {a.label}",
                f"   OCR={a.ocr_engine}  DPI={a.ocr_dpi}  marks={report['marks']['count_a']}  "
                f"quality={report['quality']['a']}",
                f"B: {b.id}",
                f"   {b.label}",
                f"   OCR={b.ocr_engine}  DPI={b.ocr_dpi}  marks={report['marks']['count_b']}  "
                f"quality={report['quality']['b']}",
                "",
                f"Пересечение марок: {report['marks']['intersection']}",
                f"Jaccard: {report['marks']['jaccard']:.2%}",
                f"Recall A←B: {report['marks']['recall_a_vs_b']}",
                f"Recall B←A: {report['marks']['recall_b_vs_a']}",
                f"Winner (quality): {report['quality']['winner']}",
                f"Δ marks: {report['metrics_delta']['marks_count']:+d}  "
                f"Δ text_chars: {report['metrics_delta']['text_chars']:+d}  "
                f"Δ quality: {report['metrics_delta']['quality_score']:+.3f}",
                "",
                "=== Только в A ===",
                *([f"  {m}" for m in report["marks"]["only_a"]] or ["  —"]),
                "",
                "=== Только в B ===",
                *([f"  {m}" for m in report["marks"]["only_b"]] or ["  —"]),
                "",
                "=== Организации: только A ===",
                *([f"  {m}" for m in report["organizations"]["only_a"]] or ["  —"]),
                "",
                "=== Организации: только B ===",
                *([f"  {m}" for m in report["organizations"]["only_b"]] or ["  —"]),
            ]
            text = "\n".join(lines)
            self.compare_report.delete("1.0", "end")
            self.compare_report.insert("1.0", text)
            _log.info("compared snapshots %s vs %s jaccard=%.3f", a.id, b.id, report["marks"]["jaccard"])
            self.status.set(f"Сравнение: Jaccard {report['marks']['jaccard']:.0%}")
        except Exception as exc:
            _log.exception("compare failed")
            messagebox.showerror("Сравнение", str(exc))

    def _make_scrollable_tab(self, parent: ttk.Frame) -> ttk.Frame:
        """Canvas + Scrollbar + inner Frame для длинных вкладок (Настройки)."""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            outer,
            highlightthickness=0,
            borderwidth=0,
            bg=COLORS["bg"],
        )
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfigure(win_id, width=max(1, int(event.width)))

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._settings_canvas = canvas
        self._settings_scroll_inner = inner
        self._settings_scroll_outer = outer
        self._settings_wheel_bound = False
        return inner

    def _widget_is_under(self, widget: tk.Misc | None, ancestor: tk.Misc) -> bool:
        cur: tk.Misc | None = widget
        while cur is not None:
            if cur == ancestor:
                return True
            cur = getattr(cur, "master", None)
        return False

    def _settings_wheel_target_is_nested(self, widget: tk.Misc) -> bool:
        """Над Treeview/Text/Spinbox — колесо для вложенного скролла, не вкладки."""
        cur: tk.Misc | None = widget
        outer = getattr(self, "_settings_scroll_outer", None)
        while cur is not None:
            if outer is not None and cur == outer:
                return False
            cls = cur.winfo_class()
            if cls in ("Treeview", "Listbox", "Spinbox", "TSpinbox"):
                return True
            if cls == "Text":
                # Если весь текст уже виден — крутим вкладку, иначе — сам Text.
                try:
                    first, last = cur.yview()  # type: ignore[attr-defined]
                    if float(first) <= 0.001 and float(last) >= 0.999:
                        return False
                except (tk.TclError, TypeError, ValueError):
                    pass
                return True
            cur = getattr(cur, "master", None)
        return False

    def _on_settings_mousewheel(self, event: tk.Event) -> str | None:
        canvas = getattr(self, "_settings_canvas", None)
        outer = getattr(self, "_settings_scroll_outer", None)
        if canvas is None or outer is None:
            return None
        # Только когда курсор над вкладкой «Настройки» (не unbind на Leave дочерних).
        if not self._widget_is_under(event.widget, outer):
            # Windows: event.widget иногда root — проверяем координаты
            try:
                x, y = outer.winfo_pointerxy()
                under = outer.winfo_containing(x, y)
                if under is None or not self._widget_is_under(under, outer):
                    return None
                widget = under
            except tk.TclError:
                return None
        else:
            widget = event.widget
        if self._settings_wheel_target_is_nested(widget):
            return None
        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            return None
        canvas.yview_scroll(int(-1 * (delta / 120)), "units")
        return "break"

    def _enable_settings_wheel(self) -> None:
        if getattr(self, "_settings_wheel_bound", False):
            return
        self.bind_all("<MouseWheel>", self._on_settings_mousewheel, add="+")
        self._settings_wheel_bound = True

    def _disable_settings_wheel(self) -> None:
        if not getattr(self, "_settings_wheel_bound", False):
            return
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        self._settings_wheel_bound = False

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        if not self.notebook:
            return
        selected = self.notebook.index(self.notebook.select())
        # Колесо для длинной вкладки «Настройки» (bind_all, без срыва на дочерних Entry).
        if selected == self.notebook.index(self.tab_settings):
            self._enable_settings_wheel()
            self._load_mappings_table()
        else:
            self._disable_settings_wheel()
            if selected == self.notebook.index(self.tab_kp):
                self._load_kp_calculations()
            elif selected == self.notebook.index(self.tab_orgs):
                self._load_orgs_table()
            elif selected == self.notebook.index(self.tab_orders):
                self._load_orders_table()
            elif selected == self.notebook.index(self.tab_compare):
                if not getattr(self, "_compare_list_loaded", False):
                    self._refresh_compare_list()
                    self._compare_list_loaded = True
                else:
                    self._refresh_compare_list()
            elif hasattr(self, "tab_journal") and selected == self.notebook.index(
                self.tab_journal
            ):
                self._load_journal_tail()

    def _build_settings_tab(self) -> None:
        # Прокручиваемый контейнер: иначе map_frame.expand съедает верх (LLM, путь).
        body = self._make_scrollable_tab(self.tab_settings)

        frame = ttk.LabelFrame(
            body,
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

        llm_frame = ttk.LabelFrame(
            body,
            text="ИИ-ассистент (LLM / Ollama)",
            padding=16,
            style="Card.TLabelframe",
        )
        llm_frame.pack(fill="x", pady=(12, 0))
        self.llm_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            llm_frame,
            text="Включить LLM поверх детерминированных подсказок (opt-in)",
            variable=self.llm_enabled_var,
        ).pack(anchor="w")

        llm_grid = ttk.Frame(llm_frame, style="Card.TFrame")
        llm_grid.pack(fill="x", pady=(10, 0))
        from ..config import OLLAMA_MODELS_DIR_DEFAULT

        self.llm_model_var = tk.StringVar(value="llama3.2")
        self.llm_base_url_var = tk.StringVar(value="http://127.0.0.1:11434")
        self.llm_models_dir_var = tk.StringVar(value=OLLAMA_MODELS_DIR_DEFAULT)
        self.llm_timeout_var = tk.StringVar(value="60")
        for row, (label, var, width) in enumerate(
            (
                ("Модель:", self.llm_model_var, 28),
                ("URL Ollama:", self.llm_base_url_var, 40),
                ("Каталог моделей (OLLAMA_MODELS):", self.llm_models_dir_var, 40),
                ("Таймаут, с:", self.llm_timeout_var, 8),
            )
        ):
            ttk.Label(llm_grid, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky="w", pady=4, padx=(0, 10)
            )
            ttk.Entry(llm_grid, textvariable=var, width=width).grid(
                row=row, column=1, sticky="ew", pady=4
            )
        llm_grid.columnconfigure(1, weight=1)

        llm_btns = ttk.Frame(llm_frame, style="Card.TFrame")
        llm_btns.pack(fill="x", pady=(8, 0))
        ttk.Button(llm_btns, text="Проверить Ollama", command=self._test_ollama_connection).pack(
            side="left"
        )
        ttk.Label(
            llm_frame,
            text=(
                "По умолчанию выключено. Стандартный путь моделей Windows: "
                "%USERPROFILE%\\.ollama\\models "
                "(напр. C:\\Users\\User\\.ollama\\models). "
                "Модель: llama3.2 → ollama pull llama3.2"
            ),
            style="CardMuted.TLabel",
            wraplength=720,
        ).pack(anchor="w", pady=(8, 0))

        battle_frame = ttk.LabelFrame(
            body,
            text="Боевой опыт — перенос на машину разработки",
            padding=16,
            style="Card.TLabelframe",
        )
        battle_frame.pack(fill="x", pady=(12, 0))
        self.battle_note_var = tk.StringVar()
        ttk.Label(
            battle_frame,
            text="После работы на другом ПК: экспорт zip → на флешку/Git → импорт у разработчика.",
            style="CardMuted.TLabel",
            wraplength=720,
        ).pack(anchor="w")
        note_row = ttk.Frame(battle_frame, style="Card.TFrame")
        note_row.pack(fill="x", pady=(8, 0))
        ttk.Label(note_row, text="Комментарий к экспорту:", style="Card.TLabel").pack(side="left")
        ttk.Entry(note_row, textvariable=self.battle_note_var, width=48).pack(
            side="left", fill="x", expand=True, padx=(8, 0), ipady=2
        )
        battle_btns = ttk.Frame(battle_frame, style="Card.TFrame")
        battle_btns.pack(fill="x", pady=(10, 0))
        ttk.Button(
            battle_btns,
            text="Экспорт опыта (zip)…",
            command=self._export_battle_experience_dialog,
        ).pack(side="left")
        ttk.Button(
            battle_btns,
            text="Импорт опыта…",
            command=self._import_battle_experience_dialog,
        ).pack(side="left", padx=(8, 0))
        self.battle_host_label = ttk.Label(
            battle_frame,
            text="",
            style="CardMuted.TLabel",
        )
        self.battle_host_label.pack(anchor="w", pady=(8, 0))
        self._refresh_battle_host_label()

        pack_frame = ttk.LabelFrame(
            body,
            text="Пакет документов — папка сохранения",
            padding=16,
            style="Card.TLabelframe",
        )
        pack_frame.pack(fill="x", pady=(12, 0))
        self.pack_base_dir_var = tk.StringVar()
        dir_row = ttk.Frame(pack_frame, style="Card.TFrame")
        dir_row.pack(fill="x")
        ttk.Label(dir_row, text="Базовая папка:", style="Card.TLabel").pack(side="left")
        ttk.Entry(dir_row, textvariable=self.pack_base_dir_var, width=52).pack(
            side="left", fill="x", expand=True, padx=(8, 6), ipady=2
        )
        ttk.Button(dir_row, text="Обзор…", command=self._browse_pack_base_dir).pack(side="left")
        recent_row = ttk.Frame(pack_frame, style="Card.TFrame")
        recent_row.pack(fill="x", pady=(10, 0))
        ttk.Label(recent_row, text="Недавние:", style="Card.TLabel").pack(side="left")
        self.pack_recent_var = tk.StringVar()
        self.pack_recent_combo = ttk.Combobox(
            recent_row,
            textvariable=self.pack_recent_var,
            width=58,
            state="readonly",
        )
        self.pack_recent_combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.pack_recent_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._apply_recent_pack_path(),
        )
        ttk.Label(
            pack_frame,
            text="Пустая базовая папка → data/generated. Имя подпапки задаётся при сборке пакета.",
            style="CardMuted.TLabel",
            wraplength=720,
        ).pack(anchor="w", pady=(8, 0))

        # Фиксированная высота таблицы: не expand=True на всю вкладку (съедало верх).
        map_frame = ttk.LabelFrame(
            body,
            text="Маппинг требований → испытания (test_mappings)",
            padding=12,
            style="Card.TLabelframe",
        )
        map_frame.pack(fill="x", pady=(12, 0))

        map_toolbar = ttk.Frame(map_frame)
        map_toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(map_toolbar, text="Обновить", command=self._load_mappings_table).pack(side="left")
        ttk.Button(map_toolbar, text="Добавить…", command=self._add_mapping_dialog).pack(
            side="left", padx=6
        )
        ttk.Button(map_toolbar, text="Изменить…", command=self._edit_mapping_dialog).pack(
            side="left", padx=0
        )
        ttk.Button(map_toolbar, text="Удалить", command=self._delete_mapping).pack(side="left", padx=6)
        ttk.Label(
            map_toolbar,
            text="Фраза из заявки → код испытания. Двойной клик — изменить.",
            style="Muted.TLabel",
        ).pack(side="right")

        self.mappings_search_var = tk.StringVar()
        self.mappings_search_var.trace_add("write", lambda *_: self._load_mappings_table())
        search_row = ttk.Frame(map_frame)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="Поиск:").pack(side="left")
        ttk.Entry(search_row, textvariable=self.mappings_search_var, width=40).pack(
            side="left", padx=8, ipady=2
        )

        map_tree_row = ttk.Frame(map_frame)
        map_tree_row.pack(fill="x")
        map_cols = ("pattern", "test_code", "usage", "note")
        self.mappings_tree = ttk.Treeview(
            map_tree_row,
            columns=map_cols,
            show="headings",
            height=8,
            selectmode="browse",
        )
        for col, title, width, anchor in (
            ("pattern", "Фраза требования", 360, "w"),
            ("test_code", "Код испытания", 220, "w"),
            ("usage", "×", 40, "center"),
            ("note", "Примечание", 200, "w"),
        ):
            self.mappings_tree.heading(col, text=title, anchor=anchor)
            self.mappings_tree.column(col, width=width, anchor=anchor)
        map_scroll = ttk.Scrollbar(map_tree_row, orient="vertical", command=self.mappings_tree.yview)
        self.mappings_tree.configure(yscrollcommand=map_scroll.set)
        self.mappings_tree.pack(side="left", fill="x", expand=True)
        map_scroll.pack(side="right", fill="y")
        self.mappings_tree.bind("<Double-1>", lambda _e: self._edit_mapping_dialog())

        hint = self._make_readonly_text(
            body,
            height=4,
            font=("Segoe UI", 10),
            bg="#f8fafc",
            relief="flat",
        )
        hint.pack(fill="x", pady=8)
        self._set_text(
            hint,
            "Часы выдержки — для климатики (time_based).\n"
            "Маппинг — подсказки на вкладке «Расчёт» (кнопка «Испытания из заявки»). "
            "Счётчик × растёт при применении маппинга из БД.",
        )
        self._load_mappings_table()

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

    def _set_text(self, widget: scrolledtext.ScrolledText, content: str) -> None:
        """Записать текст; readonly-поля (_rp_readonly) остаются копируемыми."""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        if getattr(widget, "_rp_readonly", False):
            return
        widget.configure(state="disabled")

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
                text = format_breakdown(calc) + f"\n\n✓ Сохранено в БД (id={calc_id})"
                self.after(0, lambda: self._show_calc_result_mode(text))
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
        self._show_calc_picker_mode()
        self._set_text(self.calc_output, "")
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
        from ..assistant.mark_corrector import get_mark_corrector
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

    def _refresh_marks_tree(self) -> None:
        if not hasattr(self, "marks_tree"):
            return
        for item in self.marks_tree.get_children():
            self.marks_tree.delete(item)
        if not self._extraction_draft:
            self._assistant_hints = {}
            return
        # лёгкий rebuild подсказок (детерминированный, быстрый)
        self._rebuild_assistant_hints()
        for idx, mark in enumerate(self._extraction_draft.marks):
            accepted = "✓" if mark.accepted else "—"
            doc = mark.document or ""
            size_text = ""
            if mark.characteristic_size is not None:
                unit = "мм²" if mark.size_unit == "mm2" else "мм"
                size_text = f"{mark.characteristic_size:g}{unit}"
            has_hint = idx in self._assistant_hints
            self.marks_tree.insert(
                "",
                "end",
                iid=str(idx),
                tags=(self._mark_tree_tag(mark, has_hint=has_hint),),
                values=(
                    accepted,
                    "💡" if has_hint else "",
                    mark.mark,
                    mark.brand or "",
                    str(mark.cores_count or ""),
                    size_text,
                    doc,
                    self._status_icon(mark.status),
                    f"{mark.confidence:.0%}",
                ),
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

        # Между opts и mid: pack с before=mid, чтобы mid не уезжал без expand
        mid = getattr(self, "_pdf_mid_pane", None)
        if mid is not None and mid.winfo_manager():
            self.validation_warn_frame.pack(
                fill="x", pady=(0, 4), before=mid
            )
        else:
            self.validation_warn_frame.pack(
                fill="x", pady=(0, 4), after=self.pdf_opts_frame
            )

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
        enabled = state == "normal"
        for btn in (getattr(self, "confirm_btn", None), getattr(self, "confirm_btn_top", None)):
            self._set_button_enabled(btn, enabled)

    def _update_validation_status_bar(
        self,
        *,
        state: str,
        file_name: str = "",
        result: PdfExtractionResult | None = None,
        report: ValidationReport | None = None,
    ) -> None:
        colors = {
            "idle": COLORS["muted"],
            "draft": COLORS["draft_accent"],
            "confirmed": COLORS["confirmed_accent"],
            "error": "#dc2626",
        }
        self.validation_status_bar.configure(bg=colors.get(state, COLORS["muted"]))

        if state == "idle":
            self.validation_status_var.set("Документ не обработан — выберите файл и нажмите «Извлечь»")
            self._set_confirm_buttons_state("disabled")
            return

        if state == "error":
            self.validation_status_var.set("Ошибка извлечения — попробуйте «Перепарсить»")
            self._set_confirm_buttons_state("disabled")
            return

        parts: list[str] = []
        if state == "draft":
            parts.append("ЧЕРНОВИК")
        elif state == "confirmed":
            parts.append("✓ ПОДТВЕРЖДЕНО")

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
            accepted = sum(1 for m in self._extraction_draft.marks if m.accepted) if self._extraction_draft else 0
            parts.append(f"{accepted} марок")
            parts.append(f"уверенность {report.overall_confidence:.0%}")
            if report.document_type != "unknown":
                parts.append(report.document_type)

        self.validation_status_var.set("  ·  ".join(parts))
        if state == "draft" and report:
            self._set_confirm_buttons_state("normal" if not report.block_confirm else "disabled")
        elif state == "confirmed":
            self._set_confirm_buttons_state("disabled")

    def _fill_draft_org_fields(self, draft: ExtractionDraft) -> None:
        report = draft.report
        self.draft_customer_var.set(report.customer_name)
        self.draft_manufacturer_var.set(report.manufacturer_name)
        self.draft_recipient_var.set(report.recipient_name or "—")

        customer_org = next((o for o in report.organizations if o.role == "customer"), None)
        self.draft_customer_inn_var.set(customer_org.inn if customer_org and customer_org.inn else "")
        addr = ""
        if customer_org and customer_org.address:
            from ..extraction.organization_extractor import finalize_organization_address
            from ..models import OrganizationExtract

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

    def _show_extraction_draft(self, draft: ExtractionDraft) -> None:
        self._extraction_draft = draft
        self._extraction_confirmed = False
        self._refresh_marks_tree()
        self._fill_draft_org_fields(draft)
        self._apply_test_type_from_document(draft.result.text)
        self._update_validation_warnings(draft.report)
        self._set_text(self.mark_context_text, "")
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
            from ..assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
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
            from ..assistant.mark_corrector import get_mark_corrector
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
        from ..assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
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
        from ..assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
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

        from ..assistant.mark_corrector import get_mark_corrector
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
        if not self._extraction_draft:
            return
        sel = self.marks_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._extraction_draft.marks):
            self._set_text(
                self.mark_context_text,
                self._format_mark_context_panel(self._extraction_draft.marks[idx]),
            )

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
        accepted = [
            CableMarkMatch(mark=m.mark, context=m.context, document=m.document)
            for m in self._extraction_draft.marks
            if m.accepted
        ]
        customer_name = self.draft_customer_var.get().strip()
        manufacturer_name = self.draft_manufacturer_var.get().strip()
        customer_inn = self.draft_customer_inn_var.get().strip() or None
        customer_addr = self.draft_customer_addr_var.get().strip() or None

        organizations = []
        for org in self._extraction_draft.result.organizations:
            org_copy = org.model_copy(deep=True)
            if org_copy.role == "customer":
                if customer_name:
                    org_copy.name = customer_name
                if customer_inn:
                    org_copy.inn = customer_inn
                if customer_addr:
                    org_copy.address = customer_addr
            elif org_copy.role == "manufacturer" and manufacturer_name:
                org_copy.name = manufacturer_name
            organizations.append(org_copy)

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
        if not lines:
            return
        out_dir = Path("data/training/corrections")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{Path(result.source_path).stem}.jsonl"
        out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

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
        if self.save_orgs_var.get() and result.organizations:
            org_ids = save_organizations_from_extraction(
                result.organizations,
                source=str(result.source_path),
                db_path=self.db_path,
            )
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
        self._set_text(self.mark_context_text, "")
        self._update_validation_status_bar(state="idle")
        self.parse_info_var.set("Заявка не обработана — вкладка «1. Заявка»")
        self.status.set("Черновик отменён")

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
                        from ..assistant.mark_corrector import suggest_mark_correction, get_mark_corrector
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
                    from ..extraction.pdf_extractor import extract_from_text
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
                "Выберите файл PDF или Word.\n"
                "Или нажмите «Текст…» для ввода речи/письма заказчика.",
            )
            return

        eng = "torch-CV" if self.ocr_pytorch_var.get() else "OCR"
        try:
            dpi_show = int(self.ocr_dpi_var.get())
        except (TypeError, ValueError, tk.TclError):
            dpi_show = SCAN_OCR_DPI
        self.status.set(f"Извлечение заявки… ({eng}, DPI {dpi_show})")
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
                from ..extraction.pdf_extractor import extract_from_document
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

    def _kp_subject_text(self) -> str:
        return build_kp_subject(test_type=self.kp_test_type_var.get())

    def _apply_test_type_from_document(self, text: str | None) -> None:
        label = format_test_type_label(detect_test_type(text))
        self.kp_test_type_var.set(label)
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
            messagebox.showwarning(
                "КП",
                "Сначала подтвердите заявку на вкладке «1. Заявка» "
                "(кнопка «Принять и сохранить»).",
            )
            return

        customer = self.kp_customer_var.get().strip()
        subject = self._kp_subject_text()
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
                style = (
                    self.kp_style_var.get().strip()
                    if hasattr(self, "kp_style_var")
                    else None
                )
                saved_path = generate_kp_from_db(
                    customer=customer,
                    subject=subject,
                    calculation_ids=ids,
                    output_path=out_file,
                    db_path=self.db_path,
                    note=note,
                    style=style,
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
            f"Вид испытаний: {details.get('subject') or '—'}",
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

    def _export_order_protocol_meta(self) -> None:
        """JSON без измерений для D:\\My_projects\\protocol_generator."""
        order_id = self._get_selected_order_id()
        if order_id is None:
            messagebox.showinfo("JSON протокола", "Выберите заказ.")
            return
        self.status.set("Экспорт JSON для protocol_generator…")
        self.update_idletasks()

        def work() -> None:
            path: Path | None = None
            error: str | None = None
            try:
                from ..generation.protocol_meta_export import export_protocol_meta_for_order

                path = export_protocol_meta_for_order(order_id, db_path=self.db_path)
            except Exception as exc:
                error = str(exc)

            def done() -> None:
                if error or path is None:
                    self.status.set("Ошибка экспорта JSON")
                    messagebox.showerror("JSON протокола", error or "unknown")
                    return
                self.status.set(f"JSON: {path.name}")
                _log.info(
                    "protocol meta exported order=%s path=%s",
                    order_id,
                    path,
                    extra={"tag": "Протокол"},
                )
                messagebox.showinfo(
                    "JSON для protocol_generator",
                    f"Сохранено (без измеренных значений):\n{path}\n\n"
                    "На машине с protocol_generator:\n"
                    f'  cd D:\\My_projects\\protocol_generator\n'
                    f'  .\\venv\\Scripts\\python.exe main.py "{path}"\n\n'
                    "Или: scripts\\run_protocol_from_json.ps1",
                )
                try:
                    import os

                    os.startfile(str(path.parent))
                except OSError:
                    pass

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

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
                from ..generation.application_generator import generate_application_from_order
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

    def _generate_order_protocol(self) -> None:
        order_id = self._get_selected_order_id()
        if order_id is None:
            return
        self.status.set("Формирование макета протокола…")
        self.update_idletasks()

        def work() -> None:
            saved_path: Path | None = None
            error: str | None = None
            try:
                from ..generation.protocol_generator import generate_protocol_draft_from_order
                saved_path = generate_protocol_draft_from_order(
                    order_id, db_path=self.db_path
                )
            except Exception as exc:
                error = str(exc)

            def done() -> None:
                if error:
                    self.status.set("Ошибка макета протокола")
                    messagebox.showerror("Макет протокола", error)
                    return
                assert saved_path is not None
                self.status.set(f"Заказ №{order_id} · протокол: {saved_path.name}")
                try:
                    import os

                    os.startfile(str(saved_path))
                except OSError:
                    pass
                messagebox.showinfo(
                    "Макет протокола",
                    f"Черновик протокола сохранён:\n{saved_path}\n\n"
                    "Доработайте результаты испытаний вручную.",
                )

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _build_order_document_pack(self) -> None:
        """North Star: заявка + КП + макет протокола + summary в одну папку."""
        order_id = self._get_selected_order_id()
        if order_id is None:
            return
        opts = self._ask_document_pack_options(order_id)
        if not opts:
            return
        pack_settings = get_document_pack_settings(self.db_path)
        pack_settings.base_dir = opts["output_dir"]
        save_document_pack_settings(pack_settings, self.db_path)
        if hasattr(self, "pack_base_dir_var"):
            self.pack_base_dir_var.set(opts["output_dir"])

        self.status.set("Сборка пакета документов…")
        self.update_idletasks()

        def work() -> None:
            pack: dict | None = None
            error: str | None = None
            try:
                from ..generation.document_pack import build_document_pack
                pack = build_document_pack(
                    order_id,
                    output_dir=opts["output_dir"],
                    pack_folder_name=opts["pack_folder_name"],
                    db_path=self.db_path,
                )
                push_recent_pack_path(pack["pack_dir"], self.db_path)
            except Exception as exc:
                error = str(exc)

            def done() -> None:
                if error or not pack:
                    self.status.set("Ошибка пакета документов")
                    messagebox.showerror("Пакет документов", error or "Неизвестная ошибка")
                    return
                pack_dir = pack["pack_dir"]
                self.status.set(f"Заказ №{order_id} · пакет: {Path(pack_dir).name}")
                self._load_orders_table()
                self._show_order_details()
                self._load_settings()
                try:
                    import os

                    os.startfile(pack_dir)
                except OSError:
                    pass
                names = "\n".join(f"  • {Path(f).name}" for f in pack.get("files") or [])
                messagebox.showinfo(
                    "Пакет документов",
                    f"Папка:\n{pack_dir}\n\n{names}\n\n"
                    "Макет протокола — черновик; ТУ/ПМИ-выдержки — в следующих итерациях.",
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
        self._refresh_calc_picker()

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

    def _toggle_pdf_opts(self) -> None:
        """Показать/скрыть блок OCR и флагов сохранения."""
        if not hasattr(self, "pdf_opts_frame"):
            return
        if self._pdf_opts_expanded:
            self.pdf_opts_frame.pack_forget()
            self._pdf_opts_expanded = False
            return
        try:
            self.pdf_opts_frame.pack(fill="x", pady=8, before=self._pdf_mid_pane)
        except (tk.TclError, AttributeError):
            self.pdf_opts_frame.pack(fill="x", pady=8)
        self._pdf_opts_expanded = True

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

    def _delete_selected_order(self) -> None:
        sel = self.orders_tree.selection()
        if not sel:
            messagebox.showinfo("Заказы", "Выберите заказ.")
            return
        order_id = int(sel[0])
        if not messagebox.askyesno(
            "Удалить заказ",
            f"Удалить заказ №{order_id}?\n\n"
            "Каскадно: позиции заказа, заявки на испытания;\n"
            "записи generated отвяжутся. Файлы КП на диске и расчёты\n"
            "в «Истории» не удаляются автоматически.",
        ):
            return
        result = delete_order(order_id, self.db_path, cascade=True)
        if result.get("ok"):
            self._load_orders_table()
            self._set_text(self.order_details, "")
            self.status.set(f"Заказ №{order_id} удалён")
            _log.info("deleted order id=%s", order_id, extra={"tag": "БД"})
        else:
            messagebox.showerror("Заказы", f"Не удалось: {result.get('reason')}")

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

    def _load_settings(self) -> None:
        settings = get_climatic_settings(self.db_path) or ClimaticTestSettings()
        for key, var in self.setting_vars.items():
            var.set(str(getattr(settings, key)))
        if hasattr(self, "llm_enabled_var"):
            llm = get_assistant_llm_settings(self.db_path)
            self.llm_enabled_var.set(llm.enabled)
            self.llm_model_var.set(llm.model)
            self.llm_base_url_var.set(llm.base_url)
            self.llm_models_dir_var.set(llm.ollama_models_dir)
            self.llm_timeout_var.set(str(llm.timeout_seconds))
        if hasattr(self, "pack_base_dir_var"):
            pack = get_document_pack_settings(self.db_path)
            self.pack_base_dir_var.set(pack.base_dir or str(self.generated_dir))
            recent = pack.recent_paths or []
            self.pack_recent_combo.configure(values=recent)
            if recent:
                self.pack_recent_var.set(recent[0])

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
        if hasattr(self, "llm_enabled_var"):
            try:
                from ..config import OLLAMA_MODELS_DIR_DEFAULT

                llm = AssistantLlmSettings(
                    enabled=self.llm_enabled_var.get(),
                    provider="ollama" if self.llm_enabled_var.get() else "off",
                    model=self.llm_model_var.get().strip() or "llama3.2",
                    base_url=self.llm_base_url_var.get().strip() or "http://127.0.0.1:11434",
                    ollama_models_dir=(
                        self.llm_models_dir_var.get().strip() or OLLAMA_MODELS_DIR_DEFAULT
                    ),
                    timeout_seconds=float(self.llm_timeout_var.get().replace(",", ".")),
                )
            except ValueError:
                messagebox.showerror("LLM", "Укажите корректный таймаут (число секунд).")
                return
            save_assistant_llm_settings(llm, self.db_path)
        if hasattr(self, "pack_base_dir_var"):
            pack = get_document_pack_settings(self.db_path)
            pack.base_dir = self.pack_base_dir_var.get().strip()
            save_document_pack_settings(pack, self.db_path)
        self.status.set("Настройки сохранены")

    def _refresh_battle_host_label(self) -> None:
        if not hasattr(self, "battle_host_label"):
            return
        try:
            from ..training.battle_experience import get_battle_host_id

            host_id = get_battle_host_id(self.db_path)
            self.battle_host_label.configure(
                text=f"ID этой станции: {host_id}  (префикс файлов при импорте у разработчика)"
            )
        except Exception:  # noqa: BLE001
            self.battle_host_label.configure(text="")

    def _export_battle_experience_dialog(self) -> None:
        from datetime import datetime

        from ..training.battle_experience import export_battle_experience, get_battle_host_id

        host = get_battle_host_id(self.db_path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"battle_{host}_{stamp}.zip"
        path = filedialog.asksaveasfilename(
            title="Экспорт боевого опыта",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
            initialfile=default_name,
            initialdir=str(self.generated_dir.parent / "training" / "exports"),
        )
        if not path:
            return
        try:
            result = export_battle_experience(
                path,
                db_path=self.db_path,
                operator_note=self.battle_note_var.get().strip(),
            )
            counts = result["manifest"].get("counts") or {}
            summary = ", ".join(f"{k}={v}" for k, v in counts.items())
            messagebox.showinfo(
                "Экспорт опыта",
                f"Сохранено:\n{result['path']}\n\n{summary}",
            )
            self.status.set(f"Экспорт опыта: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Экспорт опыта", str(exc))

    def _import_battle_experience_dialog(self) -> None:
        from ..training.battle_experience import import_battle_experience

        path = filedialog.askopenfilename(
            title="Импорт боевого опыта",
            filetypes=[("ZIP", "*.zip")],
        )
        if not path:
            return
        try:
            result = import_battle_experience(path, db_path=self.db_path)
            stats = result.get("stats") or {}
            host = (result.get("manifest") or {}).get("host_name", "?")
            messagebox.showinfo(
                "Импорт опыта",
                f"Источник: {host}\n"
                f"Правок скопировано: {stats.get('corrections_copied', 0)}\n"
                f"Снимков: {stats.get('snapshots_copied', 0)}",
            )
            self.status.set(f"Импорт опыта с {host}")
        except Exception as exc:
            messagebox.showerror("Импорт опыта", str(exc))

    def _test_ollama_connection(self) -> None:
        from ..assistant.llm_provider import normalize_ollama_base_url

        if hasattr(self, "llm_enabled_var"):
            try:
                base = normalize_ollama_base_url(self.llm_base_url_var.get())
                self.llm_base_url_var.set(base)
                from ..config import OLLAMA_MODELS_DIR_DEFAULT

                llm = AssistantLlmSettings(
                    enabled=True,
                    model=self.llm_model_var.get().strip() or "llama3.2",
                    base_url=base,
                    ollama_models_dir=(
                        self.llm_models_dir_var.get().strip() or OLLAMA_MODELS_DIR_DEFAULT
                    ),
                    timeout_seconds=float(self.llm_timeout_var.get().replace(",", ".")),
                )
            except ValueError:
                messagebox.showerror("Ollama", "Укажите корректный таймаут.")
                return
        else:
            llm = get_assistant_llm_settings(self.db_path)
        # Долгая проверка + автозапуск serve — не блокируем UI сообщением «висит».
        self.status.set("Проверка Ollama…")
        self.update_idletasks()
        from ..assistant.llm_provider import check_ollama_health
        health = check_ollama_health(llm, try_start=True)
        if health.ok:
            models_preview = ", ".join(health.models[:8]) if health.models else "—"
            messagebox.showinfo(
                "Ollama",
                f"{health.message}\n\nМодели: {models_preview}",
            )
            self.status.set("Ollama доступна")
        else:
            messagebox.showerror("Ollama", health.message)
            self.status.set("Ollama недоступна")

    def _browse_pack_base_dir(self) -> None:
        from tkinter import filedialog

        initial = self.pack_base_dir_var.get().strip() or str(self.generated_dir)
        path = filedialog.askdirectory(
            title="Базовая папка для пакетов документов",
            initialdir=initial if Path(initial).is_dir() else str(self.generated_dir),
        )
        if path:
            self.pack_base_dir_var.set(path)

    def _apply_recent_pack_path(self) -> None:
        selected = self.pack_recent_var.get().strip()
        if selected:
            self.pack_base_dir_var.set(str(Path(selected).parent))

    def _suggest_pack_folder_name(self, order_id: int) -> str:
        details = get_order_details(order_id, self.db_path) or {}
        customer = (details.get("customer_name") or "заказчик")[:24]
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        safe = re.sub(r'[<>:"/\\|?*«»]', "_", customer).strip("._ ") or "заказ"
        return f"pack_order{order_id}_{safe}_{stamp}"

    def _ask_document_pack_options(self, order_id: int) -> dict[str, str] | None:
        """Диалог: базовая папка + имя подпапки пакета."""
        pack_settings = get_document_pack_settings(self.db_path)
        default_base = pack_settings.base_dir.strip() or str(self.generated_dir)

        dlg = tk.Toplevel(self)
        dlg.title(f"Пакет документов · заказ №{order_id}")
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=COLORS["bg"])
        frame = ttk.Frame(dlg, padding=16, style="Card.TFrame")
        frame.pack(fill="both", expand=True)

        base_var = tk.StringVar(value=default_base)
        name_var = tk.StringVar(value=self._suggest_pack_folder_name(order_id))

        ttk.Label(frame, text="Сохранить в папку:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        base_row = ttk.Frame(frame, style="Card.TFrame")
        base_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        base_entry = ttk.Entry(base_row, textvariable=base_var, width=48)
        base_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            base_row,
            text="Обзор…",
            command=lambda: self._browse_into_var(base_var, "Папка для пакета"),
        ).pack(side="left", padx=(6, 0))

        if pack_settings.recent_paths:
            ttk.Label(frame, text="Недавние пакеты:", style="CardMuted.TLabel").grid(
                row=2, column=0, sticky="w"
            )
            recent_var = tk.StringVar()
            recent_cb = ttk.Combobox(
                frame,
                textvariable=recent_var,
                values=pack_settings.recent_paths,
                width=54,
                state="readonly",
            )
            recent_cb.grid(row=3, column=0, sticky="ew", pady=(2, 10))

            def _use_recent(_e: object = None) -> None:
                p = recent_var.get().strip()
                if p:
                    base_var.set(str(Path(p).parent))

            recent_cb.bind("<<ComboboxSelected>>", _use_recent)

        ttk.Label(frame, text="Имя папки пакета:", style="Card.TLabel").grid(
            row=4, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(frame, textvariable=name_var, width=54).grid(
            row=5, column=0, sticky="ew", pady=(0, 16)
        )

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
            result["output_dir"] = base
            result["pack_folder_name"] = name
            dlg.destroy()

        def _cancel() -> None:
            dlg.destroy()

        btns = ttk.Frame(frame, style="Card.TFrame")
        btns.grid(row=6, column=0, sticky="w")
        self._accent_button(btns, "Собрать", _ok).pack(side="left")
        ttk.Button(btns, text="Отмена", command=_cancel).pack(side="left", padx=8)

        dlg.update_idletasks()
        w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        dlg.geometry(f"+{x}+{y}")
        dlg.wait_window()
        return result or None

    def _browse_into_var(self, var: tk.StringVar, title: str) -> None:
        from tkinter import filedialog

        initial = var.get().strip() or str(self.generated_dir)
        path = filedialog.askdirectory(
            title=title,
            initialdir=initial if Path(initial).is_dir() else str(self.generated_dir),
        )
        if path:
            var.set(path)

    def _show_orders_context_menu(self, event: tk.Event) -> None:
        row = self.orders_tree.identify_row(event.y)
        if row:
            self.orders_tree.selection_set(row)
        order_id = self._get_selected_order_id()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Открыть КП", command=self._open_selected_order_kp)
        menu.add_command(label="Открыть заявку", command=self._open_selected_order_application)
        menu.add_command(label="Сформировать заявку", command=self._generate_order_application)
        menu.add_command(label="Пакет документов…", command=self._build_order_document_pack)
        menu.add_command(label="Макет протокола", command=self._generate_order_protocol)
        menu.add_separator()
        if order_id is not None:
            menu.add_command(
                label=f"Копировать № заказа ({order_id})",
                command=lambda: self._copy_text_to_clipboard(str(order_id)),
            )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_text_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.set("Скопировано в буфер обмена")

    def _load_mappings_table(self) -> None:
        if not hasattr(self, "mappings_tree"):
            return
        for item in self.mappings_tree.get_children():
            self.mappings_tree.delete(item)
        search = self.mappings_search_var.get().strip().lower() if hasattr(self, "mappings_search_var") else ""
        rows = list_test_mappings(limit=500, db_path=self.db_path)
        for row in rows:
            pattern = row.get("requirement_pattern") or ""
            code = row.get("test_code") or ""
            note = row.get("note") or ""
            if search and search not in pattern.lower() and search not in code.lower() and search not in note.lower():
                continue
            self.mappings_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(pattern, code, row.get("usage_count", 0), note),
            )

    def _selected_mapping_id(self) -> int | None:
        sel = self.mappings_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _mapping_test_codes(self) -> list[str]:
        rows = list_test_items(limit=500, db_path=self.db_path)
        return sorted({row["code"] for row in rows if row.get("code")})

    def _open_mapping_editor(
        self,
        *,
        mapping_id: int | None,
        title: str,
        save_label: str,
    ) -> None:
        initial_pattern = ""
        initial_code = ""
        initial_note = ""
        if mapping_id is not None:
            rows = list_test_mappings(limit=500, db_path=self.db_path)
            row = next((r for r in rows if r["id"] == mapping_id), None)
            if row:
                initial_pattern = row.get("requirement_pattern") or ""
                initial_code = row.get("test_code") or ""
                initial_note = row.get("note") or ""

        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("520x260")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()

        pattern_var = tk.StringVar(value=initial_pattern)
        code_var = tk.StringVar(value=initial_code)
        note_var = tk.StringVar(value=initial_note)
        codes = self._mapping_test_codes()

        ttk.Label(dialog, text="Фраза из заявки (подстрока):").grid(
            row=0, column=0, sticky="w", padx=12, pady=8
        )
        ttk.Entry(dialog, textvariable=pattern_var, width=48).grid(
            row=0, column=1, sticky="ew", padx=12, pady=8
        )
        ttk.Label(dialog, text="Код испытания:").grid(row=1, column=0, sticky="w", padx=12, pady=8)
        ttk.Combobox(
            dialog,
            textvariable=code_var,
            values=codes,
            width=46,
        ).grid(row=1, column=1, sticky="ew", padx=12, pady=8)
        ttk.Label(dialog, text="Примечание:").grid(row=2, column=0, sticky="w", padx=12, pady=8)
        ttk.Entry(dialog, textvariable=note_var, width=48).grid(
            row=2, column=1, sticky="ew", padx=12, pady=8
        )

        def save() -> None:
            pattern = pattern_var.get().strip()
            code = code_var.get().strip()
            note = note_var.get().strip() or None
            if not pattern or not code:
                messagebox.showwarning("Маппинг", "Укажите фразу и код испытания.", parent=dialog)
                return
            try:
                if mapping_id is None:
                    add_test_mapping(pattern, code, note=note, db_path=self.db_path)
                else:
                    update_test_mapping(
                        mapping_id,
                        requirement_pattern=pattern,
                        test_code=code,
                        note=note,
                        db_path=self.db_path,
                    )
            except Exception as exc:
                messagebox.showerror("Маппинг", str(exc), parent=dialog)
                return
            dialog.destroy()
            self._load_mappings_table()
            self.status.set("Маппинг сохранён")

        ttk.Button(dialog, text=save_label, style="Accent.TButton", command=save).grid(
            row=3, column=0, columnspan=2, pady=14
        )
        dialog.columnconfigure(1, weight=1)

    def _add_mapping_dialog(self) -> None:
        self._open_mapping_editor(mapping_id=None, title="Новый маппинг", save_label="Добавить")

    def _edit_mapping_dialog(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            messagebox.showinfo("Маппинг", "Выберите строку в таблице.")
            return
        self._open_mapping_editor(
            mapping_id=mapping_id,
            title="Изменить маппинг",
            save_label="Сохранить",
        )

    def _delete_mapping(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            messagebox.showinfo("Маппинг", "Выберите строку для удаления.")
            return
        if not messagebox.askyesno("Маппинг", "Удалить выбранный маппинг?"):
            return
        if delete_test_mapping(mapping_id, self.db_path):
            self._load_mappings_table()
            self.status.set("Маппинг удалён")
        else:
            messagebox.showerror("Маппинг", "Запись не найдена.")

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
    t0 = time.perf_counter()
    enable_windows_dpi_awareness()
    setup_logging(level="INFO")
    _log.info("main(): starting Lab_request", extra={"tag": "Старт"})
    app = RequestProcessorApp()
    _log.info(
        "mainloop in %.0f ms",
        (time.perf_counter() - t0) * 1000,
        extra={"tag": "Старт"},
    )
    app.mainloop()


if __name__ == "__main__":
    main()