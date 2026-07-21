"""Mixin: ClipboardMixin — domain methods for Lab_request GUI."""

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

class ClipboardMixin:
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
        # Readonly ScrolledText (контекст марки и т.п.) — только копирование
        if getattr(widget, "_rp_readonly", False):
            return False
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

    def _copy_text_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.set("Скопировано в буфер обмена")

