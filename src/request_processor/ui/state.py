"""Shared GUI state models and constants."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from ..models import (
    AssistantLlmSettings,
    MarkValidation,
    PdfExtractionResult,
    ValidationReport,
)
from ..assistant.feedback import AssistantFeedbackEvent

ORG_TYPE_LABELS: dict[str, str] = {
    "manufacturer": "Производитель",
    "certification_body": "Орган по сертификации",
    "testing_center": "Испытательный центр",
    "dealer": "Дилер",
    "unknown": "Не указан",
}
ORG_TYPE_VALUES = list(ORG_TYPE_LABELS.keys())


class RequestPageState(str, Enum):
    """
    Состояния страницы «Заявки» (единый render_state).

    Не путать с бизнес-разделами Расчёт / КП / Заказ:
    это этапы обработки одного документа-заявки.
    """

    EMPTY = "empty"
    FILE_SELECTED = "file_selected"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    READY_TO_CONFIRM = "ready_to_confirm"
    CONFIRMED = "confirmed"
    ERROR = "error"


# Человекочитаемые статусы + тон бейджа (grey/blue/orange/green/red)
REQUEST_STATUS_UI: dict[RequestPageState, tuple[str, str]] = {
    RequestPageState.EMPTY: ("Не обработана", "grey"),
    RequestPageState.FILE_SELECTED: ("Документ выбран", "blue"),
    RequestPageState.PROCESSING: ("Распознавание", "blue"),
    RequestPageState.REVIEW_REQUIRED: ("Требует проверки", "orange"),
    RequestPageState.READY_TO_CONFIRM: ("Готова к подтверждению", "orange"),
    RequestPageState.CONFIRMED: ("Подтверждена", "green"),
    RequestPageState.ERROR: ("Ошибка", "red"),
}

# Индекс этапа StepIndicator (0..3)
REQUEST_STEP_INDEX: dict[RequestPageState, int] = {
    RequestPageState.EMPTY: 0,
    RequestPageState.FILE_SELECTED: 0,
    RequestPageState.PROCESSING: 1,
    RequestPageState.REVIEW_REQUIRED: 2,
    RequestPageState.READY_TO_CONFIRM: 2,
    RequestPageState.CONFIRMED: 3,
    RequestPageState.ERROR: 0,
}


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
    original_manufacturer: str = ""
    assistant_events: list[AssistantFeedbackEvent] = field(default_factory=list)
    assistant_session_id: str = ""
