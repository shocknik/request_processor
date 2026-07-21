"""Mixin: CompareTabMixin — domain methods for Lab_request GUI."""

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

class CompareTabMixin:
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
        from ...parse_compare import list_snapshots

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
            from ...parse_compare import save_snapshot_from_extraction

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
            from ...parse_compare import compare_snapshots, load_snapshot

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

