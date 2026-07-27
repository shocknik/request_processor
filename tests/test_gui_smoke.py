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
    assert len(tabs) == 11
    # v0.10: sidebar navigation + hidden notebook tabs
    assert getattr(gui_app, "sidebar", None) is not None
    assert hasattr(gui_app, "page_header")
    assert hasattr(gui_app, "step_indicator")
    assert hasattr(gui_app, "upload_panel")
    assert hasattr(gui_app, "bottom_bar")
    assert hasattr(gui_app, "render_request_state")


def test_gui_tab_titles(gui_app: RequestProcessorApp) -> None:
    titles = [gui_app.notebook.tab(tab_id, "text").strip() for tab_id in gui_app.notebook.tabs()]
    assert "1. Заявка" in titles
    assert "2. Расчёт" in titles
    assert "3. КП" in titles
    assert "4. Заказы" in titles
    assert "Сравнение" in titles
    assert "Программы" in titles
    assert "Справочник" in titles
    assert "Журнал" not in titles


def test_gui_sidebar_navigation(gui_app: RequestProcessorApp) -> None:
    """Сайдбар переключает notebook; menubar API (select) тоже работает."""
    gui_app.go_section("orders")
    assert gui_app.notebook.index(gui_app.notebook.select()) == gui_app.notebook.index(
        gui_app.tab_orders
    )
    gui_app.notebook.select(gui_app.tab_kp)
    gui_app.update_idletasks()
    # после select сайдбар синхронизируется в _on_tab_changed
    assert gui_app.notebook.index(gui_app.notebook.select()) == gui_app.notebook.index(
        gui_app.tab_kp
    )


def test_request_page_state_empty(gui_app: RequestProcessorApp) -> None:
    from request_processor.ui.state import RequestPageState

    assert gui_app._request_page_state == RequestPageState.EMPTY
    assert gui_app.bottom_bar.primary_btn.cget("text") == "Извлечь данные"
    # empty state поверх таблицы
    assert hasattr(gui_app, "marks_empty")


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


def test_calc_picker_has_search_and_category(gui_app: RequestProcessorApp) -> None:
    """Вкладка Расчёт: поиск + категория; radio-режимов нет (они обнуляли список)."""
    assert hasattr(gui_app, "calc_picker_search_var")
    assert hasattr(gui_app, "calc_picker_category_var")
    # mode_var может остаться для совместимости, но UI radio не фильтрует
    gui_app.mark_var.set("ВВГнг(А) 3х1,5")
    gui_app._refresh_calc_picker()
    assert hasattr(gui_app, "_calc_picker_visible_codes")
    n_catalog = len(gui_app._tests_by_code)
    if n_catalog:
        assert len(gui_app._calc_picker_visible_codes) == n_catalog
    gui_app.calc_picker_search_var.set("zzz_no_match_xyz")
    gui_app._refresh_calc_picker()
    assert gui_app._calc_picker_visible_codes == []
    gui_app.calc_picker_search_var.set("")
    gui_app._refresh_calc_picker()
    if n_catalog:
        assert len(gui_app._calc_picker_visible_codes) == n_catalog
    # смена «режима» (если var ещё есть) не должна прятать прайс
    if hasattr(gui_app, "calc_picker_mode_var"):
        gui_app.calc_picker_mode_var.set("selected")
        gui_app._refresh_calc_picker()
        if n_catalog:
            assert len(gui_app._calc_picker_visible_codes) == n_catalog
        gui_app.calc_picker_mode_var.set("suggested")
        gui_app._refresh_calc_picker()
        if n_catalog:
            assert len(gui_app._calc_picker_visible_codes) == n_catalog


def _seed_picker_tests(gui_app: RequestProcessorApp) -> None:
    """Мини-прайс в _tests_by_code (smoke.db пустой — без этого фильтр не проверяется)."""
    gui_app._tests_by_code = {
        "admin_base": {
            "code": "admin_base",
            "name": "Базовая стоимость",
            "category": "Административная работа",
            "rule_type": "fixed",
            "rule_params": "{}",
        },
        "prep_samples": {
            "code": "prep_samples",
            "name": "Базовая подготовка образцов",
            "category": "Подготовка к испытаниям",
            "rule_type": "fixed",
            "rule_params": "{}",
        },
        "prep_armor": {
            "code": "prep_armor",
            "name": "Удаление брони",
            "category": "Подготовка к испытаниям",
            "rule_type": "fixed",
            "rule_params": "{}",
        },
        "prep_vna": {
            "code": "prep_vna",
            "name": "Установка соединителей (под VNA, AESA)",
            "category": "Подготовка к испытаниям",
            "rule_type": "fixed",
            "rule_params": "{}",
        },
        "elec_res": {
            "code": "elec_res",
            "name": "Электрическое сопротивление ТПЖ",
            "category": "Электрические параметры НЧ",
            "rule_type": "per_core",
            "rule_params": "{}",
        },
    }
    gui_app._update_picker_category_combo()


def test_calc_picker_category_filter(gui_app: RequestProcessorApp) -> None:
    """Категория сужает список; «Все» снова полный каталог.

    Источник фильтра — _picker_active_category (не StringVar combobox):
    Windows ttk после configure(values) сбрасывает var в «Все», из‑за этого
    раньше combobox показывал категорию, а список оставался 61/61.
    """
    _seed_picker_tests(gui_app)
    gui_app.mark_var.set("Тест марка")
    gui_app.calc_picker_search_var.set("")
    gui_app._picker_active_category = "Все"
    gui_app._sync_picker_category_display("Все")
    gui_app._refresh_calc_picker()
    n_all = len(gui_app._calc_picker_visible_codes)
    assert n_all == len(gui_app._tests_by_code) == 5

    cat0 = "Подготовка к испытаниям"
    # как в UI: ComboboxSelected / выбор пользователем
    gui_app.calc_picker_category_var.set(cat0)
    gui_app.calc_picker_category_combo.set(cat0)
    gui_app._on_picker_category_selected()
    n_cat = len(gui_app._calc_picker_visible_codes)
    assert n_cat == 3, (
        f"категория {cat0!r} дала {n_cat} из {n_all}; "
        f"active={gui_app._picker_active_category!r} "
        f"var={gui_app.calc_picker_category_var.get()!r} "
        f"codes={gui_app._calc_picker_visible_codes!r}"
    )
    assert all(
        (gui_app._tests_by_code[c].get("category") or "Без категории").strip() == cat0
        for c in gui_app._calc_picker_visible_codes
    )
    assert gui_app._picker_active_category == cat0
    assert gui_app.calc_picker_category_var.get() == cat0

    # combobox event path (другая категория)
    gui_app.calc_picker_category_var.set("Административная работа")
    gui_app.calc_picker_category_combo.set("Административная работа")
    gui_app._on_picker_category_selected()
    assert len(gui_app._calc_picker_visible_codes) == 1
    assert gui_app._calc_picker_visible_codes == ["admin_base"]

    # поиск не сбрасывает категорию
    gui_app.calc_picker_search_var.set("базов")
    gui_app.update()
    assert gui_app._picker_active_category == "Административная работа"
    assert gui_app._calc_picker_visible_codes == ["admin_base"]

    # регрессия: Windows сбросил var в «Все», active остаётся — фильтр жив
    gui_app.calc_picker_search_var.set("")
    gui_app._picker_active_category = "Подготовка к испытаниям"
    gui_app.calc_picker_category_var.set("Все")  # как после configure(values)
    gui_app._refresh_calc_picker()
    assert len(gui_app._calc_picker_visible_codes) == 3, (
        "фильтр должен читать _picker_active_category, а не сброшенный combobox var"
    )
    assert gui_app._picker_active_category == "Подготовка к испытаниям"
    # display восстановлен из active
    assert gui_app.calc_picker_category_var.get() == "Подготовка к испытаниям"

    gui_app.calc_picker_category_var.set("Все")
    gui_app.calc_picker_category_combo.set("Все")
    gui_app._on_picker_category_selected()
    assert len(gui_app._calc_picker_visible_codes) == n_all
    assert gui_app._picker_active_category == "Все"


def test_calc_picker_category_survives_windows_var_reset(
    gui_app: RequestProcessorApp,
) -> None:
    """После выбора категории повторный refresh/configure не снимает фильтр."""
    _seed_picker_tests(gui_app)
    gui_app.mark_var.set("X")
    gui_app.calc_picker_category_combo.set("Электрические параметры НЧ")
    gui_app._on_picker_category_selected()
    assert gui_app._picker_active_category == "Электрические параметры НЧ"
    assert len(gui_app._calc_picker_visible_codes) == 1

    # имитация: Windows обнулил var, search debounce дернул refresh
    gui_app.calc_picker_category_var.set("Все")
    for _ in range(3):
        gui_app._update_picker_category_combo()
        gui_app._refresh_calc_picker()
    assert gui_app._picker_active_category == "Электрические параметры НЧ"
    assert gui_app._calc_picker_visible_codes == ["elec_res"]
    assert gui_app.calc_picker_category_var.get() == "Электрические параметры НЧ"


def _assert_picker_checkbuttons_visible(
    gui_app: RequestProcessorApp,
    expected_codes: list[str] | set[str],
) -> list[str]:
    """Проверить, что у видимых кодов есть mapped Checkbutton с ненулевым размером."""
    expected = list(expected_codes)
    cbs = getattr(gui_app, "_calc_picker_checkbuttons", {})
    assert set(cbs.keys()) == set(expected), (
        f"checkbuttons={sorted(cbs.keys())} expected={sorted(expected)}"
    )
    gui_app.update_idletasks()
    gui_app._finish_picker_geometry()
    gui_app.update_idletasks()
    for code in expected:
        cb = cbs[code]
        assert cb.winfo_exists(), code
        assert cb.winfo_ismapped(), f"{code} not mapped"
        assert cb.winfo_width() > 1, f"{code} width={cb.winfo_width()}"
        assert cb.winfo_height() > 1, f"{code} height={cb.winfo_height()}"
    return expected


def test_calc_picker_category_rows_are_visible_and_clickable(
    gui_app: RequestProcessorApp,
) -> None:
    """Регрессия: фильтр даёт 3 Checkbutton; invoke ставит галочку и добавляет слева."""
    _seed_picker_tests(gui_app)
    gui_app.deiconify()
    gui_app.go_section("calc")
    gui_app.update()

    category = "Подготовка к испытаниям"
    gui_app.calc_picker_category_combo.set(category)
    gui_app.calc_picker_category_combo.event_generate(
        "<<ComboboxSelected>>",
        when="tail",
    )
    gui_app.update()

    assert gui_app._picker_active_category == category
    assert len(gui_app._calc_picker_visible_codes) == 3
    assert "показано 3 / в прайсе 5" in gui_app.calc_picker_list_stats_var.get()

    shown_codes = list(gui_app._calc_picker_visible_codes)
    _assert_picker_checkbuttons_visible(gui_app, shown_codes)
    assert not any(code.startswith("admin") for code in shown_codes)

    # пользовательский путь: invoke Checkbutton (не прямой set var)
    first_code = shown_codes[0]
    first_cb = gui_app._calc_picker_checkbuttons[first_code]
    first_cb.invoke()
    gui_app.update_idletasks()
    assert any(entry.code == first_code for entry in gui_app._calc_entries)
    assert gui_app._calc_picker_vars[first_code].get() is True

    gui_app._picker_select_visible()
    assert {entry.code for entry in gui_app._calc_entries} == set(shown_codes)

    # сохранение галочки после смены категории
    armor = "prep_armor"
    assert gui_app._calc_picker_vars[armor].get() is True
    gui_app.calc_picker_category_combo.set("Административная работа")
    gui_app._on_picker_category_selected()
    assert gui_app._calc_picker_visible_codes == ["admin_base"]
    gui_app.calc_picker_category_combo.set(category)
    gui_app._on_picker_category_selected()
    assert set(gui_app._calc_picker_visible_codes) == set(shown_codes)
    assert gui_app._calc_picker_vars[armor].get() is True
    assert any(e.code == armor for e in gui_app._calc_entries)

    gui_app.calc_picker_search_var.set("VNA")
    gui_app._refresh_calc_picker()
    assert gui_app._picker_active_category == category
    assert gui_app._calc_picker_visible_codes == ["prep_vna"]
    _assert_picker_checkbuttons_visible(gui_app, ["prep_vna"])

    for width in (1100, 1450, 1200):
        gui_app.geometry(f"{width}x800")
        gui_app.update()
        gui_app._finish_picker_geometry()
        gui_app.update_idletasks()
        assert gui_app._calc_picker_visible_codes == ["prep_vna"]
        _assert_picker_checkbuttons_visible(gui_app, ["prep_vna"])


def test_calc_picker_real_catalog_preparation_has_exact_three(
    gui_app: RequestProcessorApp,
) -> None:
    """Seed-прайс: категория подготовки показывает ровно три production-кода."""
    expected = {
        "базовая_подготовка_образцов",
        "удаление_брони",
        "установка_соединителейпод_vna_aesa",
    }
    if len(gui_app._tests_by_code) != 61:
        pytest.skip(f"smoke.db без полного прайса n={len(gui_app._tests_by_code)}")

    gui_app.deiconify()
    gui_app.go_section("calc")
    gui_app.calc_picker_category_combo.set("Подготовка к испытаниям")
    gui_app.calc_picker_category_combo.event_generate(
        "<<ComboboxSelected>>",
        when="tail",
    )
    gui_app.update()

    assert set(gui_app._calc_picker_visible_codes) == expected
    _assert_picker_checkbuttons_visible(gui_app, expected)
    # 1 заголовок категории + 3 строки (каждая строка = Frame)
    children = list(gui_app.calc_picker_inner.winfo_children())
    assert len(children) == 4, f"ожидали header+3 rows, got {len(children)}"


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