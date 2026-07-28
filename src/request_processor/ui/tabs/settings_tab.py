"""Mixin: SettingsTabMixin — domain methods for Lab_request GUI."""

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

class SettingsTabMixin:
    def _import_norm_text_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Текст ТУ / ГОСТ (.txt)",
            filetypes=[("Текст", "*.txt"), ("Все", "*.*")],
            initialdir=str(
                Path(__file__).resolve().parents[3]
                / "data"
                / "knowledge"
                / "manufacturer_v1"
                / "raw_text"
            ),
        )
        if not path:
            return
        try:
            from ...generation.norm_text_import import import_norm_from_text_file

            result = import_norm_from_text_file(path, db_path=self.db_path)
            messagebox.showinfo(
                "Нормы",
                f"{result['doc_id']}\nПунктов (эвристика): {result['clauses']}",
            )
            self.status.set(f"Норма: {result['doc_id']} ({result['clauses']} п.)")
            _log.info(
                "norm import %s clauses=%s",
                result["doc_id"],
                result["clauses"],
                extra={"tag": "Нормы"},
            )
        except Exception as exc:
            messagebox.showerror("Нормы", str(exc))

    def _import_aliases_yaml_dialog(self) -> None:
        default = (
            Path(__file__).resolve().parents[3]
            / "data"
            / "knowledge"
            / "manufacturer_v1"
            / "test_synonyms.yaml"
        )
        path = filedialog.askopenfilename(
            title="YAML синонимов",
            filetypes=[("YAML", "*.yaml;*.yml"), ("Все", "*.*")],
            initialdir=str(default.parent) if default.parent.is_dir() else None,
        )
        if not path:
            path = str(default) if default.is_file() else ""
        if not path:
            return
        try:
            from ...generation.norm_text_import import import_aliases_from_synonyms_yaml

            n = import_aliases_from_synonyms_yaml(path, db_path=self.db_path)
            messagebox.showinfo("Aliases", f"Импортировано/обновлено: {n}")
            self.status.set(f"Aliases: {n}")
        except Exception as exc:
            messagebox.showerror("Aliases", str(exc))

    def _show_norms_summary(self) -> None:
        from ...persistence.sqlite_repo import (
            list_norm_documents,
            list_requirements,
            list_test_aliases,
        )

        docs = list_norm_documents(db_path=self.db_path)
        reqs = list_requirements(limit=5, db_path=self.db_path)
        aliases = list_test_aliases(limit=8, db_path=self.db_path)
        lines = [f"Норм: {len(docs)}", ""]
        for d in docs[:12]:
            lines.append(f"  [{d['kind']}] {d['doc_id']}: {d['title'][:50]}")
        lines.append("")
        lines.append("Примеры требований:")
        for r in reqs:
            lines.append(f"  {r['doc_id']} п.{r['clause']}: {(r.get('title') or '')[:40]}")
        lines.append("")
        lines.append("Aliases:")
        for a in aliases:
            lines.append(
                f"  {a['alias_norm'][:28]} → {a.get('price_test_code') or a['canonical_name'][:24]}"
            )
        messagebox.showinfo("Нормы / aliases", "\n".join(lines) or "Пусто — migrate-db")

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
        from ...config import OLLAMA_MODELS_DIR_DEFAULT

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
        ttk.Button(
            llm_btns,
            text="S2.5 Демо: 3 OCR-марки…",
            command=self._run_s25_ocr_marks_demo,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            llm_frame,
            text=(
                "По умолчанию выключено. Стандартный путь моделей Windows: "
                "%USERPROFILE%\\.ollama\\models "
                "(напр. C:\\Users\\User\\.ollama\\models). "
                "Модель: llama3.2 → ollama pull llama3.2. "
                "S2.5 — таблица 3 OCR-марок (MarkCorrector; LLM если включён)."
            ),
            style="CardMuted.TLabel",
            wraplength=720,
        ).pack(anchor="w", pady=(8, 0))

        prod_frame = ttk.LabelFrame(
            body,
            text="Данные prod — перенос на машину разработки",
            padding=16,
            style="Card.TLabelframe",
        )
        prod_frame.pack(fill="x", pady=(12, 0))
        self.prod_note_var = tk.StringVar()
        ttk.Label(
            prod_frame,
            text="После работы на рабочем ПК: экспорт zip → флешка/сеть → импорт у разработчика "
            "(правки, снимки парсинга, feedback ассистента).",
            style="CardMuted.TLabel",
            wraplength=720,
        ).pack(anchor="w")
        note_row = ttk.Frame(prod_frame, style="Card.TFrame")
        note_row.pack(fill="x", pady=(8, 0))
        ttk.Label(note_row, text="Комментарий к экспорту:", style="Card.TLabel").pack(side="left")
        ttk.Entry(note_row, textvariable=self.prod_note_var, width=48).pack(
            side="left", fill="x", expand=True, padx=(8, 0), ipady=2
        )
        prod_btns = ttk.Frame(prod_frame, style="Card.TFrame")
        prod_btns.pack(fill="x", pady=(10, 0))
        ttk.Button(
            prod_btns,
            text="Экспорт данных prod (zip)…",
            command=self._export_prod_data_dialog,
        ).pack(side="left")
        ttk.Button(
            prod_btns,
            text="Импорт данных prod…",
            command=self._import_prod_data_dialog,
        ).pack(side="left", padx=(8, 0))
        self.prod_station_label = ttk.Label(
            prod_frame,
            text="",
            style="CardMuted.TLabel",
        )
        self.prod_station_label.pack(anchor="w", pady=(8, 0))
        self._refresh_prod_station_label()

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
                from ...config import OLLAMA_MODELS_DIR_DEFAULT

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

    def _run_s25_ocr_marks_demo(self) -> None:
        """S2.5: таблица 3 OCR-марок — MarkCorrector (+ LLM если opt-in)."""
        from ...assistant.demo_marks import (
            format_demo_table,
            run_ocr_marks_demo,
            save_demo_report,
        )

        try:
            report = run_ocr_marks_demo(db_path=self.db_path, record_feedback=True)
            path = save_demo_report(report)
        except Exception as exc:
            messagebox.showerror("S2.5 демо", str(exc))
            return

        table = format_demo_table(report)
        c = report.get("counts") or {}
        dlg = tk.Toplevel(self)
        dlg.title("S2.5 — демо 3 OCR-марки")
        dlg.geometry("820x420")
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(
            dlg,
            text=(
                f"helped yes={c.get('helped_yes')} partial={c.get('helped_partial')} "
                f"no={c.get('helped_no')} · llm={c.get('llm_source')} · "
                f"отчёт: {path.name}"
            ),
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", padx=12, pady=(12, 4))
        txt = scrolledtext.ScrolledText(dlg, wrap="none", height=16, font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=12, pady=4)
        txt.insert("1.0", table)
        txt.configure(state="disabled")
        ttk.Button(dlg, text="Закрыть", command=dlg.destroy).pack(pady=10)
        self.status.set(f"S2.5 демо: yes={c.get('helped_yes')}/3 · {path.name}")
        _log.info(
            "S2.5 demo yes=%s partial=%s no=%s llm=%s path=%s",
            c.get("helped_yes"),
            c.get("helped_partial"),
            c.get("helped_no"),
            c.get("llm_source"),
            path,
            extra={"tag": "Ассистент"},
        )

    def _refresh_prod_station_label(self) -> None:
        if not hasattr(self, "prod_station_label"):
            return
        try:
            from ...training.prod_data import get_prod_station_id

            station_id = get_prod_station_id(self.db_path)
            self.prod_station_label.configure(
                text=f"ID этой станции: {station_id}  (префикс файлов при импорте у разработчика)"
            )
        except Exception:  # noqa: BLE001
            self.prod_station_label.configure(text="")

    def _export_prod_data_dialog(self) -> None:
        from datetime import datetime

        from ...training.prod_data import export_prod_data, get_prod_station_id

        station = get_prod_station_id(self.db_path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"prod_data_{station}_{stamp}.zip"
        path = filedialog.asksaveasfilename(
            title="Экспорт данных prod",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
            initialfile=default_name,
            initialdir=str(self.generated_dir.parent / "training" / "exports"),
        )
        if not path:
            return
        try:
            result = export_prod_data(
                path,
                db_path=self.db_path,
                operator_note=self.prod_note_var.get().strip(),
            )
            counts = result["manifest"].get("counts") or {}
            summary = ", ".join(f"{k}={v}" for k, v in counts.items())
            messagebox.showinfo(
                "Экспорт данных prod",
                f"Сохранено:\n{result['path']}\n\n{summary}",
            )
            self.status.set(f"Экспорт данных prod: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Экспорт данных prod", str(exc))

    def _import_prod_data_dialog(self) -> None:
        from ...training.prod_data import import_prod_data

        path = filedialog.askopenfilename(
            title="Импорт данных prod",
            filetypes=[("ZIP", "*.zip")],
        )
        if not path:
            return
        try:
            result = import_prod_data(path, db_path=self.db_path)
            stats = result.get("stats") or {}
            host = (result.get("manifest") or {}).get("host_name", "?")
            messagebox.showinfo(
                "Импорт данных prod",
                f"Источник: {host}\n"
                f"Правок скопировано: {stats.get('corrections_copied', 0)}\n"
                f"Снимков: {stats.get('snapshots_copied', 0)}",
            )
            self.status.set(f"Импорт данных prod с {host}")
        except Exception as exc:
            messagebox.showerror("Импорт данных prod", str(exc))

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

    def _browse_into_var(self, var: tk.StringVar, title: str) -> None:
        from tkinter import filedialog

        initial = var.get().strip() or str(self.generated_dir)
        path = filedialog.askdirectory(
            title=title,
            initialdir=initial if Path(initial).is_dir() else str(self.generated_dir),
        )
        if path:
            var.set(path)

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

        from ..modal import create_modal, present_modal

        dialog = create_modal(self, title=title, minsize=(480, 220))

        pattern_var = tk.StringVar(master=dialog, value=initial_pattern)
        code_var = tk.StringVar(master=dialog, value=initial_code)
        note_var = tk.StringVar(master=dialog, value=initial_note)
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
        present_modal(dialog, prefer_w=520, prefer_h=260)

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

