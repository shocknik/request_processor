"""Регрессия: extract → review/confirm → марка → расчёт.

Ловит сценарий 2026-07-27: DOCX-направление с текстом в таблицах,
длинное «Общество с ограниченной…», disabled «Подтвердить заявку».
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from request_processor.extraction.organization_extractor import _clean_org_name
from request_processor.extraction.pdf_extractor import extract_from_document
from request_processor.models import (
    CableMarkMatch,
    FieldStatus,
    MarkValidation,
    OrganizationExtract,
    PdfExtractionResult,
    ValidationReport,
)
from request_processor.ui.extract_job import prepare_extraction_draft
from request_processor.ui.state import ExtractionDraft, RequestPageState
from request_processor.validation.extraction_validator import (
    detect_document_type,
    validate_extraction,
)

pytest.importorskip("tkinter")

from request_processor.ui.gui import RequestProcessorApp


@pytest.fixture
def gui_app(tmp_path):
    try:
        app = RequestProcessorApp(db_path=tmp_path / "workflow.db")
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter недоступен: {exc}")
        raise
    app.withdraw()
    yield app
    app.destroy()


_DOCX = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "training"
    / "documents"
    / "registered"
    / "03.04.2025-2СЕРК Направление в ИЛ 10067087.docx"
)


def test_clean_org_name_full_legal_form_no_double_ooo() -> None:
    raw = (
        "Общество с ограниченной ответственностью "
        "«Производственное объединение «Энергокомплект»"
    )
    cleaned = _clean_org_name(raw)
    assert cleaned.startswith("ООО")
    assert "Общество с ограниченной" not in cleaned
    assert "Энергокомплект" in cleaned
    assert len(cleaned) <= 80

    doubled = f"ООО «{raw}»"
    cleaned2 = _clean_org_name(doubled)
    assert cleaned2.count("ООО") == 1
    assert "Общество с ограниченной" not in cleaned2


@pytest.mark.skipif(not _DOCX.is_file(), reason="training docx not on disk")
def test_docx_table_only_result_text_and_no_block_confirm() -> None:
    """Word-направление: текст в таблицах → result.text полный, confirm не блокируется."""
    result = extract_from_document(_DOCX, use_ocr=False)
    assert len(result.text or "") > 500, f"text too short: {len(result.text or '')}"
    assert detect_document_type(result.text) == "direction"
    assert result.customer_name
    assert "Общество с ограниченной" not in (result.customer_name or "")
    assert len(result.customer_name or "") <= 80
    assert len(result.cable_marks) >= 1

    report = validate_extraction(result)
    assert report.document_type == "direction"
    assert report.block_confirm is False, report.flags
    assert any(m.accepted for m in report.marks)


@pytest.mark.skipif(not _DOCX.is_file(), reason="training docx not on disk")
def test_prepare_draft_enables_confirm_path() -> None:
    result = extract_from_document(_DOCX, use_ocr=False)
    draft = prepare_extraction_draft(
        result,
        source_path=_DOCX,
        json_stem="workflow_confirm_smoke",
    )
    assert draft.report.block_confirm is False
    assert sum(1 for m in draft.marks if m.accepted) >= 1


def test_gui_confirm_primary_enabled_even_with_block_flag(gui_app) -> None:
    """Кнопка «Подтвердить» кликабельна при block_confirm — диалог объясняет блок."""
    report = ValidationReport(
        overall_confidence=0.4,
        document_type="direction",
        customer_name="X" * 100,
        manufacturer_name="",
        recipient_name="",
        flags=["P0-3: слишком длинное имя заказчика"],
        marks=[
            MarkValidation(
                mark="ВВГ 3х1,5",
                confidence=0.8,
                status=FieldStatus.warning,
                warnings=["P1-3: ТУ/ГОСТ не извлечён"],
                accepted=True,
            )
        ],
        block_confirm=True,
        organizations=[],
    )
    result = PdfExtractionResult(
        source_path="virt.docx",
        source_type="docx",
        text="НАПРАВЛЕНИЕ\nиспытательная лаборатория\nВВГ 3х1,5",
        page_count=1,
        cable_marks=[CableMarkMatch(mark="ВВГ 3х1,5")],
        organizations=[
            OrganizationExtract(name="X" * 100, role="customer", confidence=0.5)
        ],
        customer_name="X" * 100,
    )
    draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("virt.docx"),
        json_path=None,
        marks=list(report.marks),
        original_marks=[m.model_copy(deep=True) for m in report.marks],
        original_customer=result.customer_name or "",
        original_manufacturer="",
    )
    gui_app._show_extraction_draft(draft)
    gui_app._update_validation_status_bar(
        state="draft",
        file_name="virt.docx",
        result=result,
        report=report,
    )
    assert gui_app._request_page_state in (
        RequestPageState.REVIEW_REQUIRED,
        RequestPageState.READY_TO_CONFIRM,
    )
    # primary должна быть enabled (не «серый» блок без объяснения)
    assert str(gui_app.bottom_bar.primary_btn.cget("state")) == "normal"
    assert "Подтвердить" in str(gui_app.bottom_bar.primary_btn.cget("text"))

    with patch("request_processor.ui.tabs.pdf_tab.messagebox.showerror") as err:
        gui_app._confirm_extraction()
        assert err.called
        msg = str(err.call_args[0][1] if err.call_args[0] else err.call_args)
        assert "блок" in msg.lower() or "P0-3" in msg or "длинн" in msg.lower()


def test_gui_toggle_mark_requires_selection_and_preserves_it(gui_app) -> None:
    report = ValidationReport(
        overall_confidence=0.8,
        document_type="direction",
        customer_name="ООО «Тест»",
        marks=[
            MarkValidation(
                mark="ВВГ 3х1,5",
                confidence=0.9,
                status=FieldStatus.ok,
                accepted=True,
            ),
            MarkValidation(
                mark="ПВС 2х1,5",
                confidence=0.9,
                status=FieldStatus.ok,
                accepted=True,
            ),
        ],
        block_confirm=False,
        organizations=[],
    )
    result = PdfExtractionResult(
        source_path="t.docx",
        source_type="docx",
        page_count=1,
        text="НАПРАВЛЕНИЕ испытательная\nВВГ 3х1,5",
        cable_marks=[
            CableMarkMatch(mark="ВВГ 3х1,5"),
            CableMarkMatch(mark="ПВС 2х1,5"),
        ],
        customer_name="ООО «Тест»",
    )
    draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("t.docx"),
        json_path=None,
        marks=list(report.marks),
        original_marks=[m.model_copy(deep=True) for m in report.marks],
        original_customer="ООО «Тест»",
        original_manufacturer="",
    )
    gui_app._extraction_draft = draft
    gui_app._refresh_marks_tree()
    gui_app.update_idletasks()

    with patch("request_processor.ui.tabs.pdf_tab.messagebox.showinfo") as info:
        gui_app._toggle_draft_mark()
        assert info.called

    gui_app.marks_tree.selection_set("0")
    gui_app._toggle_draft_mark()
    assert gui_app._extraction_draft.marks[0].accepted is False
    # выделение сохранено после revalidate/refresh
    assert gui_app.marks_tree.selection()
    assert gui_app.marks_tree.selection()[0] == "0"
    # повтор — снова принять
    gui_app._toggle_draft_mark()
    assert gui_app._extraction_draft.marks[0].accepted is True


def test_gui_use_mark_in_calc_without_requirements(gui_app) -> None:
    """Марка уходит в расчёт даже без suggested_tests (ручной выбор прайса)."""
    report = ValidationReport(
        overall_confidence=0.8,
        document_type="direction",
        customer_name="ООО «Тест»",
        marks=[
            MarkValidation(
                mark="КГРвЭСТ 3*35",
                confidence=0.8,
                status=FieldStatus.warning,
                accepted=True,
                requirements_raw=None,
                suggested_tests=[],
            )
        ],
        block_confirm=False,
        organizations=[],
    )
    result = PdfExtractionResult(
        source_path="t.docx",
        source_type="docx",
        page_count=1,
        text="НАПРАВЛЕНИЕ испытательная\nКГРвЭСТ 3*35",
        cable_marks=[CableMarkMatch(mark="КГРвЭСТ 3*35")],
        customer_name="ООО «Тест»",
    )
    draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("t.docx"),
        json_path=None,
        marks=list(report.marks),
        original_marks=[m.model_copy(deep=True) for m in report.marks],
        original_customer="ООО «Тест»",
        original_manufacturer="",
    )
    gui_app._extraction_draft = draft
    gui_app._extraction_confirmed = True
    gui_app._refresh_marks_tree()
    gui_app.marks_tree.selection_set("0")
    gui_app.confirm_only_var.set(False)

    gui_app._use_mark_in_calc()
    assert gui_app.mark_var.get().startswith("КГРвЭСТ")
    assert gui_app._suggested_test_codes_for_mark(gui_app.mark_var.get()) == []
    # без модального окна — статус-подсказка
    assert "расчёт" in (gui_app.status.get() or "").lower() or "марк" in (
        gui_app.status.get() or ""
    ).lower()
