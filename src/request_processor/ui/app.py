"""RequestProcessorApp — shell + tab mixins."""
from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from datetime import datetime
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
from .state import ORG_TYPE_LABELS, ORG_TYPE_VALUES, CalcTestEntry, ExtractionDraft
from .widgets.clipboard import ClipboardMixin
from .shell.app_shell import ShellMixin
from .tabs.pdf_tab import PdfTabMixin
from .tabs.calc_tab import CalcTabMixin
from .tabs.kp_tab import KpTabMixin
from .tabs.orders_tab import OrdersTabMixin
from .tabs.compare_tab import CompareTabMixin
from .tabs.marks_tab import MarksTabMixin
from .tabs.orgs_tab import OrgsTabMixin
from .tabs.tests_tab import TestsTabMixin
from .tabs.history_tab import HistoryTabMixin
from .tabs.settings_tab import SettingsTabMixin
from .tabs.programs_tab import ProgramsTabMixin

_log = get_logger("ui.gui")
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


class RequestProcessorApp(
    ClipboardMixin,
    PdfTabMixin,
    CalcTabMixin,
    KpTabMixin,
    OrdersTabMixin,
    CompareTabMixin,
    MarksTabMixin,
    OrgsTabMixin,
    TestsTabMixin,
    HistoryTabMixin,
    SettingsTabMixin,
    ProgramsTabMixin,
    ShellMixin,
    tk.Tk,
):
    _CLIPBOARD_CLASSES = (
        "Entry",
        "TEntry",
        "Text",
        "Spinbox",
        "TSpinbox",
        "Combobox",
        "TCombobox",
    )


def main(*, use_splash: bool = True) -> None:
    """Точка входа GUI. По умолчанию — splash с этапами загрузки."""
    # Делегируем в лёгкий bootstrap (splash до тяжёлых импортов уже в gui.py)
    from .bootstrap import run_gui

    run_gui(use_splash=use_splash)


if __name__ == "__main__":
    main()
