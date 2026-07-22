"""Mixin: ShellMixin — domain methods for Lab_request GUI."""

from __future__ import annotations

import json
import os
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
from ...logging_setup import get_logger, setup_logging
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
from ..state import ORG_TYPE_LABELS, ORG_TYPE_VALUES, CalcTestEntry, ExtractionDraft, RequestPageState
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

class ShellMixin:
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
        # Иконка окна/панели задач + глобальное колесо для Canvas-скроллов
        try:
            from ...config import PROJECT_ROOT
            from ..widgets.mousewheel import install_mousewheel

            ico = PROJECT_ROOT / "assets" / "app_icon.ico"
            if ico.is_file():
                self.iconbitmap(default=str(ico))
            install_mousewheel(self)
        except Exception as exc:
            _log.debug("icon/mousewheel init: %s", exc, extra={"tag": "UI"})

        self._tests_by_code: dict[str, dict] = {}
        self._calc_entries: list[CalcTestEntry] = []
        self._calc_picker_vars: dict[str, tk.BooleanVar] = {}
        self._calc_picker_syncing: bool = False
        self.notebook: ttk.Notebook | None = None
        self.sidebar = None  # Sidebar | None — левая навигация (редизайн)
        self._last_document_extraction_id: int | None = None
        self._last_manufacturer_name: str = ""
        self._extraction_draft: ExtractionDraft | None = None
        self._extraction_confirmed: bool = False
        self._compare_snapshots_cache: list[dict] = []
        # кэш подсказок ассистента: index → suggested text (для колонки 💡)
        self._assistant_hints: dict[int, str] = {}
        self._pdf_opts_expanded = False
        # Состояние страницы «Заявки» (единый render_state)
        self._request_page_state: RequestPageState = RequestPageState.EMPTY

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
            from ...persistence.sqlite_repo import (
                _seed_default_settings,
                ensure_price_catalog,
                migrate_db,
            )

            migrate_db(self.db_path)
            ensure_price_catalog(self.db_path)
            _seed_default_settings(self.db_path)

    def _setup_theme(self) -> None:
        apply_fluent_theme(self)

    def _open_logs_folder(self) -> None:
        """Открыть data/logs в проводнике (логи вместо вкладки «Журнал»)."""
        from ...config import LOGS_DIR

        path = Path(LOGS_DIR)
        path.mkdir(parents=True, exist_ok=True)
        _log.info("open logs folder: %s", path, extra={"tag": "Лог"})
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception as exc:
            _log.warning("cannot open logs folder: %s", exc, extra={"tag": "Лог"})
            messagebox.showinfo("Логи", f"Папка логов:\n{path}", parent=self)

    def _show_log_viewer(self, lines: int = 400) -> None:
        """S2.3: просмотр хвоста app_*.log в окне (без вкладки «Журнал»)."""
        from ...config import LOGS_DIR
        from ...logging_setup import log_path_for

        log_path = log_path_for("app")
        if not log_path.is_file():
            # fallback: newest app_*.log
            candidates = sorted(Path(LOGS_DIR).glob("app_*.log"), key=lambda p: p.stat().st_mtime)
            log_path = candidates[-1] if candidates else log_path

        dlg = tk.Toplevel(self)
        dlg.title(f"Лог — {log_path.name}")
        dlg.geometry("960x560")
        dlg.configure(bg=COLORS["bg"])
        dlg.transient(self)

        bar = ttk.Frame(dlg, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text=str(log_path), style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text="Обновить", command=lambda: _load()).pack(side="right", padx=4)
        ttk.Button(bar, text="Папка…", command=self._open_logs_folder).pack(side="right")

        text = self._make_readonly_text(dlg, height=28, width=110)
        try:
            text.configure(bg="#0f172a", fg="#e2e8f0", insertbackground="#e2e8f0", font=("Consolas", 9))
        except tk.TclError:
            pass
        text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        def _load() -> None:
            if not log_path.is_file():
                self._set_text(text, f"Файл пока пуст:\n{log_path}")
                return
            try:
                raw = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = raw[-lines:] if len(raw) > lines else raw
                self._set_text(text, "\n".join(tail))
                text.see("end")
                _log.info("log viewer loaded lines=%s path=%s", len(tail), log_path, extra={"tag": "Лог"})
            except Exception as exc:
                self._set_text(text, f"Не удалось прочитать:\n{exc}")
                _log.warning("log viewer failed: %s", exc, extra={"tag": "Лог"})

        _load()

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
        """
        Shell v0.10: боковая навигация + контент (скрытый Notebook).

        Notebook сохраняется для menubar / smoke-тестов / notebook.select(),
        но вкладки визуально скрыты (стиль Hidden.TNotebook).
        """
        # Строка меню — вторичные действия (Файл / Вид / Данные / Сервис)
        from .menubar import install_menubar
        from ..widgets.sidebar import SECTION_TO_TAB, TAB_TO_SECTION, Sidebar

        install_menubar(self)

        self.status = tk.StringVar(value="Готово")
        status_wrap = tk.Frame(self, bg=COLORS["status_bg"], height=28)
        status_wrap.pack(side="bottom", fill="x")
        status_wrap.pack_propagate(False)
        ttk.Label(
            status_wrap,
            textvariable=self.status,
            anchor="w",
            padding=(18, 4),
            style="Status.TLabel",
        ).pack(fill="both", expand=True)

        # Компактная полоса последней заявки (глобальный контекст, не дублирует page header)
        parse_bar = tk.Frame(self, bg=COLORS["parse_bg"], padx=16, pady=6)
        parse_bar.pack(side="bottom", fill="x")
        tk.Frame(parse_bar, bg=COLORS["accent"], width=3).pack(side="left", fill="y", padx=(0, 10))
        parse_inner = tk.Frame(parse_bar, bg=COLORS["parse_bg"])
        parse_inner.pack(side="left", fill="x", expand=True)
        self.parse_info_var = tk.StringVar(
            value="Документ не обработан — раздел «Заявки» или меню Файл → Открыть"
        )
        self.parse_info_label = tk.Label(
            parse_inner,
            textvariable=self.parse_info_var,
            bg=COLORS["parse_bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            wraplength=1600,
            justify="left",
            anchor="w",
        )
        self.parse_info_label.pack(fill="x")
        self.bind("<Configure>", self._on_root_configure, add="+")

        # Основная область: sidebar | content
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.sidebar = Sidebar(
            body,
            on_select=self._on_sidebar_select,
            initial="pdf",
        )
        # col0 sidebar | col1 divider | col2 content
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        divider = tk.Frame(body, bg=COLORS["border"], width=1)
        divider.grid(row=0, column=1, sticky="ns")
        content_wrap = tk.Frame(body, bg=COLORS["bg"], padx=16, pady=12)
        content_wrap.grid(row=0, column=2, sticky="nsew")
        body.columnconfigure(2, weight=1)

        # Notebook со скрытыми вкладками (API + menubar + тесты)
        self.notebook = ttk.Notebook(content_wrap, style="Hidden.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        self.tab_pdf = ttk.Frame(self.notebook, padding=4)
        self.tab_calc = ttk.Frame(self.notebook, padding=10)
        self.tab_kp = ttk.Frame(self.notebook, padding=10)
        self.tab_orders = ttk.Frame(self.notebook, padding=10)
        self.tab_compare = ttk.Frame(self.notebook, padding=10)
        self.tab_marks = ttk.Frame(self.notebook, padding=10)
        self.tab_orgs = ttk.Frame(self.notebook, padding=10)
        self.tab_tests = ttk.Frame(self.notebook, padding=10)
        self.tab_history = ttk.Frame(self.notebook, padding=10)
        self.tab_settings = ttk.Frame(self.notebook, padding=10)
        self.tab_programs = ttk.Frame(self.notebook, padding=10)

        # Тексты вкладок сохраняем для smoke-тестов (title strip)
        self.notebook.add(self.tab_pdf, text="  1. Заявка  ")
        self.notebook.add(self.tab_calc, text="  2. Расчёт  ")
        self.notebook.add(self.tab_kp, text="  3. КП  ")
        self.notebook.add(self.tab_orders, text="  4. Заказы  ")
        self.notebook.add(self.tab_marks, text="  Марки  ")
        self.notebook.add(self.tab_orgs, text="  Организации  ")
        self.notebook.add(self.tab_tests, text="  Справочник  ")
        self.notebook.add(self.tab_programs, text="  Программы  ")
        self.notebook.add(self.tab_history, text="  История  ")
        self.notebook.add(self.tab_compare, text="  Сравнение  ")
        self.notebook.add(self.tab_settings, text="  Настройки  ")

        self._section_to_tab = SECTION_TO_TAB
        self._tab_to_section = TAB_TO_SECTION
        # Обратный map: widget path → section (для синхронизации сайдбара)
        self._tab_widget_to_section = {
            self.tab_pdf: "pdf",
            self.tab_calc: "calc",
            self.tab_kp: "kp",
            self.tab_orders: "orders",
            self.tab_marks: "marks",
            self.tab_orgs: "orgs",
            self.tab_programs: "programs",
            self.tab_history: "history",
            self.tab_compare: "compare",
            self.tab_settings: "settings",
            self.tab_tests: "tests",
        }

        self._build_pdf_tab()
        self._build_calc_tab()
        self._build_kp_tab()
        self._build_orders_tab()
        self._build_compare_tab()
        self._build_marks_tab()
        self._build_orgs_tab()
        self._build_tests_tab()
        self._build_history_tab()
        self._build_programs_tab()
        self._build_settings_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        _log.info(
            "UI shell redesign: sidebar + Hidden.TNotebook sections=%s",
            list(SECTION_TO_TAB.keys()),
            extra={"tag": "Старт"},
        )

    def _on_sidebar_select(self, section_id: str) -> None:
        """Клик в сайдбаре → переключение notebook (без дублирования бизнес-логики)."""
        tab_attr = self._section_to_tab.get(section_id)
        if not tab_attr or not self.notebook:
            _log.warning("sidebar select unknown section=%s", section_id, extra={"tag": "UI"})
            return
        tab = getattr(self, tab_attr, None)
        if tab is None:
            return
        try:
            self.notebook.select(tab)
            _log.info("navigate section=%s", section_id, extra={"tag": "UI"})
        except tk.TclError as exc:
            _log.warning("notebook.select failed: %s", exc, extra={"tag": "UI"})

    def go_section(self, section_id: str) -> None:
        """Публичный переход в раздел (меню, hotkeys, другие вкладки)."""
        if self.sidebar is not None:
            self.sidebar.set_active(section_id)
        self._on_sidebar_select(section_id)

    def _make_scrollable_tab(self, parent: ttk.Frame) -> ttk.Frame:
        """Canvas + Scrollbar + inner Frame для длинных вкладок (Настройки)."""
        from ..widgets.mousewheel import register_canvas_mousewheel

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
        # priority ниже, чем у вложенных canvas (орг. на Заявке)
        register_canvas_mousewheel(outer, canvas, priority=10)
        return inner

    def _widget_is_under(self, widget: tk.Misc | None, ancestor: tk.Misc) -> bool:
        cur: tk.Misc | None = widget
        while cur is not None:
            if cur == ancestor:
                return True
            cur = getattr(cur, "master", None)
        return False

    def _on_tab_changed(self, _event: tk.Event | None = None) -> None:
        if not self.notebook:
            return
        selected = self.notebook.index(self.notebook.select())
        # Синхронизация сайдбара (menubar / hotkeys / go_section из других вкладок)
        try:
            tab_widget = self.nametowidget(self.notebook.select())
            section = getattr(self, "_tab_widget_to_section", {}).get(tab_widget)
            if section and self.sidebar is not None:
                # tests нет в сайдбаре — подсветим settings/programs не трогаем
                if section in getattr(self.sidebar, "_rows", {}):
                    self.sidebar.set_active(section)
        except (tk.TclError, KeyError):
            pass

        # Колесо: глобальный MousewheelManager (не unbind_all — иначе ломает другие Canvas)
        if selected == self.notebook.index(self.tab_settings):
            self._load_mappings_table()
        elif selected == self.notebook.index(self.tab_kp):
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
        elif hasattr(self, "tab_programs") and selected == self.notebook.index(
            self.tab_programs
        ):
            self._load_programs_table()

    def _set_text(self, widget: scrolledtext.ScrolledText, content: str) -> None:
        """Записать текст; readonly-поля (_rp_readonly) остаются копируемыми."""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        if getattr(widget, "_rp_readonly", False):
            return
        widget.configure(state="disabled")

    def _apply_test_type_from_document(self, text: str | None) -> None:
        label = format_test_type_label(detect_test_type(text))
        self.kp_test_type_var.set(label)
        self._update_kp_preview()

    def _test_ollama_connection(self) -> None:
        from ...assistant.llm_provider import normalize_ollama_base_url

        if hasattr(self, "llm_enabled_var"):
            try:
                base = normalize_ollama_base_url(self.llm_base_url_var.get())
                self.llm_base_url_var.set(base)
                from ...config import OLLAMA_MODELS_DIR_DEFAULT

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
        from ...assistant.llm_provider import check_ollama_health
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

