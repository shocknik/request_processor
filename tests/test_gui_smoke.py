"""Smoke-тесты запуска GUI без отображения окна."""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")

from request_processor.ui.gui import RequestProcessorApp


@pytest.fixture
def gui_app(tmp_path):
    try:
        app = RequestProcessorApp(db_path=tmp_path / "smoke.db")
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter недоступен: {exc}")
        raise
    app.withdraw()
    yield app
    app.destroy()


def test_gui_starts_and_has_notebook(gui_app: RequestProcessorApp) -> None:
    assert gui_app.notebook is not None
    tabs = gui_app.notebook.tabs()
    assert len(tabs) == 12


def test_gui_tab_titles(gui_app: RequestProcessorApp) -> None:
    titles = [gui_app.notebook.tab(tab_id, "text").strip() for tab_id in gui_app.notebook.tabs()]
    assert "1. Заявка" in titles
    assert "2. Расчёт" in titles
    assert "3. КП" in titles
    assert "4. Заказы" in titles
    assert "5. Сравнение" in titles
    assert "10. Программы" in titles
    assert "12. Журнал" in titles


def test_gui_extraction_state_initial(gui_app: RequestProcessorApp) -> None:
    assert gui_app._extraction_draft is None
    assert gui_app._extraction_confirmed is False
    assert gui_app.ocr_var.get() is True


def test_validation_warnings_compact_not_expanded(gui_app: RequestProcessorApp) -> None:
    """Жёлтая полоса предупреждений не раздувается: свёрнута + summary."""
    from request_processor.models import FieldStatus, MarkValidation, ValidationReport

    report = ValidationReport(
        overall_confidence=0.5,
        document_type="letter",
        customer_name="Тест",
        manufacturer_name="",
        recipient_name="",
        flags=["Нет производителя", "Слабый OCR на стр. 1", "Проверьте ИНН"],
        marks=[
            MarkValidation(
                mark="ВВГ 3х1,5",
                confidence=0.4,
                status=FieldStatus.warning,
                warnings=["неполное обозначение"],
                accepted=True,
            )
        ],
        block_confirm=False,
        organizations=[],
    )
    gui_app._update_validation_warnings(report)
    assert gui_app._warn_expanded is False
    assert gui_app.validation_warn_frame.winfo_manager() == "pack"
    assert "предупр" in gui_app.validation_warn_summary_var.get().lower()
    # ScrolledText.pack управляет внешним .frame — смотрим pack_slaves родителя
    detail_frame = getattr(gui_app.validation_warn_detail, "frame", gui_app.validation_warn_detail)
    assert detail_frame not in gui_app.validation_warn_frame.pack_slaves()
    gui_app._toggle_validation_warnings()
    assert gui_app._warn_expanded is True
    assert detail_frame in gui_app.validation_warn_frame.pack_slaves()
    # mid-pane всё ещё в pack (основное окно марок не «съедено»)
    assert gui_app._pdf_mid_pane.winfo_manager() == "pack"


def test_gui_mappings_table_on_settings(gui_app: RequestProcessorApp) -> None:
    assert hasattr(gui_app, "mappings_tree")
    gui_app._load_mappings_table()
    children = gui_app.mappings_tree.get_children()
    assert len(children) >= 6


def test_settings_tab_is_scrollable(gui_app: RequestProcessorApp) -> None:
    """Вкладка «Настройки» — Canvas+scroll; LLM/путь не выталкиваются за край."""
    assert hasattr(gui_app, "_settings_canvas")
    assert hasattr(gui_app, "_settings_scroll_inner")
    assert gui_app._settings_canvas.winfo_exists()
    # Ключевые контролы существуют (видны через прокрутку)
    assert hasattr(gui_app, "llm_enabled_var")
    assert hasattr(gui_app, "pack_base_dir_var")
    assert hasattr(gui_app, "mappings_tree")
    # Таблица маппинга — фиксированная высота, не expand на всю вкладку
    assert int(gui_app.mappings_tree.cget("height")) <= 10


def test_use_mark_in_calc_from_draft(gui_app: RequestProcessorApp, tmp_path) -> None:
    from pathlib import Path

    from request_processor.models import FieldStatus, MarkValidation, PdfExtractionResult
    from request_processor.ui.gui import ExtractionDraft
    from request_processor.validation.extraction_validator import validate_extraction

    mark = MarkValidation(
        mark="ВВГнг(А) 3х4ок(N,PE)-0,66",
        document="ТУ 16-705.499-2010",
        confidence=0.9,
        status=FieldStatus.ok,
        accepted=True,
    )
    result = PdfExtractionResult(
        source_path="test.pdf",
        source_type="pdf",
        page_count=1,
        text="периодические испытания",
        cable_marks=[],
    )
    report = validate_extraction(result)
    json_path = tmp_path / "test.json"
    json_path.write_text("{}", encoding="utf-8")
    gui_app._extraction_draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("test.pdf"),
        json_path=json_path,
        marks=[mark],
        original_marks=[mark.model_copy(deep=True)],
    )
    gui_app._refresh_marks_tree()
    gui_app.marks_tree.selection_set("0")
    gui_app._extraction_confirmed = True
    gui_app._use_mark_in_calc()
    assert gui_app.mark_var.get() == mark.mark
    assert gui_app.notebook.index(gui_app.notebook.select()) == gui_app.notebook.index(
        gui_app.tab_calc
    )


def test_draft_mark_double_click_opens_editor(gui_app: RequestProcessorApp, tmp_path) -> None:
    """Двойной клик открывает редактор (не сразу в расчёт)."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from request_processor.models import FieldStatus, MarkValidation, PdfExtractionResult
    from request_processor.ui.gui import ExtractionDraft
    from request_processor.validation.extraction_validator import validate_extraction

    mark = MarkValidation(
        mark="АПуВ 1х6",
        confidence=0.9,
        status=FieldStatus.ok,
        accepted=True,
    )
    result = PdfExtractionResult(
        source_path="t.pdf",
        source_type="pdf",
        page_count=1,
        text="test",
        cable_marks=[],
    )
    report = validate_extraction(result)
    json_path = tmp_path / "t.json"
    json_path.write_text("{}", encoding="utf-8")
    gui_app._extraction_draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("t.pdf"),
        json_path=json_path,
        marks=[mark],
        original_marks=[mark.model_copy(deep=True)],
    )
    gui_app._extraction_confirmed = True
    gui_app._refresh_marks_tree()
    gui_app.marks_tree.selection_set("0")
    event = MagicMock()
    event.x = 10
    event.y = 10
    gui_app.marks_tree.identify_region = MagicMock(return_value="cell")
    gui_app.marks_tree.identify_row = MagicMock(return_value="0")
    opened: list[str] = []
    gui_app._open_mark_editor = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda *a, **k: opened.append(k.get("save_label") or "ok")
    )
    gui_app._on_draft_mark_double_click(event)
    assert gui_app._open_mark_editor.called
    assert opened and "Сохранить" in opened[0]


def test_use_mark_in_calc_from_button(gui_app: RequestProcessorApp, tmp_path) -> None:
    """Кнопка «→ В расчёт» подставляет марку в поле расчёта."""
    from pathlib import Path

    from request_processor.models import FieldStatus, MarkValidation, PdfExtractionResult
    from request_processor.ui.gui import ExtractionDraft
    from request_processor.validation.extraction_validator import validate_extraction

    mark = MarkValidation(
        mark="АПуВ 1х6",
        confidence=0.9,
        status=FieldStatus.ok,
        accepted=True,
    )
    result = PdfExtractionResult(
        source_path="t.pdf",
        source_type="pdf",
        page_count=1,
        text="test",
        cable_marks=[],
    )
    report = validate_extraction(result)
    json_path = tmp_path / "t.json"
    json_path.write_text("{}", encoding="utf-8")
    gui_app._extraction_draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("t.pdf"),
        json_path=json_path,
        marks=[mark],
        original_marks=[mark.model_copy(deep=True)],
    )
    gui_app._extraction_confirmed = True
    gui_app._refresh_marks_tree()
    gui_app.marks_tree.selection_set("0")
    gui_app._use_mark_in_calc()
    assert gui_app.mark_var.get() == "АПуВ 1х6"


def test_calc_picker_visible_before_calculate(gui_app: RequestProcessorApp) -> None:
    gui_app.mark_var.set("ВВГнг(А) 3х4")
    gui_app._refresh_calc_picker()
    assert gui_app.calc_picker_frame.winfo_manager() == "pack"
    assert gui_app.calc_result_frame.winfo_manager() != "pack"
    assert len(gui_app._calc_picker_vars) > 0


def test_calc_picker_toggle_adds_test(gui_app: RequestProcessorApp) -> None:
    codes = list(gui_app._tests_by_code.keys())
    if not codes:
        pytest.skip("нет испытаний в справочнике")
    code = codes[0]
    gui_app.mark_var.set("Тестовая марка")
    gui_app._refresh_calc_picker()
    var = gui_app._calc_picker_vars.get(code)
    assert var is not None
    var.set(True)
    gui_app._on_picker_toggle(code)
    assert any(e.code == code for e in gui_app._calc_entries)
    var.set(False)
    gui_app._on_picker_toggle(code)
    assert not any(e.code == code for e in gui_app._calc_entries)


def test_calc_result_mode_shows_summary(gui_app: RequestProcessorApp) -> None:
    gui_app._show_calc_result_mode("Итого: 1000 руб.")
    assert gui_app.calc_result_frame.winfo_manager() == "pack"
    assert gui_app.calc_picker_frame.winfo_manager() != "pack"
    gui_app._show_calc_picker_mode()
    assert gui_app.calc_picker_frame.winfo_manager() == "pack"